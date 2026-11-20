"""SSH session through a bastion host to a Junos device.

Flow (default "jump" mode)
 1. Paramiko logs in to the jump host as the P-Number with password + VIP token
    (password auth, with automatic keyboard-interactive fallback).
 2. A direct-tcpip tunnel is opened through the jump host to switch:22 (like
    `ssh -J`). The switch name is resolved by the jump host, so switches in
    the jump host's own domain work; an optional domain suffix can be added.
 3. A second SSH login runs inside the tunnel with the switch credentials
    (same P-Number/password by default, or separate ones). If the switch
    rejects them, the UI asks for a VIP code and the login is retried.
 4. When a Junos prompt (user@host> ) is seen the session is READY.

"shell" mode instead opens a shell on the bastion and types the hop command
(default `ssh {hostname}`), answering prompts automatically.

Once READY every command goes through a single queue so the background
monitoring commands and the user's own CLI commands never interleave.
Background output is captured silently; user output streams to the CLI.
"""
import codecs
import re
import socket
import threading
import time
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

from .config import KNOWN_HOSTS
from .parsers import clean_text, find_prompt, strip_command_output

DISCONNECTED, CONNECTING, HOPPING, READY = "disconnected", "connecting", "hopping", "ready"

_YESNO_RE = re.compile(r"\(yes/no[^)]*\)\??\s*$", re.I)
_LOGIN_RE = re.compile(r"(?:^|\n)\s*(?:login as|login|username)\s*:\s*$", re.I)
_PASS_RE = re.compile(r"(?:^|\n)[^\n]*(?:password|passcode)[^\n]*:\s*$", re.I)
# Bastion shell prompt, e.g. "[p1234567@jumphost01 ~]$ " – last line contains @ or ~ and ends in $ # > %
_SHELL_RE = re.compile(r"(?:^|\n)[^\n]*[@~][^\n]*[$#>%]\s*$")
_FAIL_RE = re.compile(r"(permission denied|connection refused|could not resolve|no route to host|"
                      r"connection timed out|host key verification failed|connection closed)", re.I)
EXIT_WORDS = {"exit", "quit", "logout"}


class Job:
    def __init__(self, command, background=False, callback=None, tag=None, timeout=180, help_query=False):
        self.command = command
        self.background = background
        self.callback = callback
        self.tag = tag
        self.timeout = timeout
        self.help_query = help_query
        self.buffer = ""
        self.output = ""
        self.started = None
        self.timed_out = False


class JunosSession(QObject):
    console = Signal(str)            # text for the CLI window
    state_changed = Signal(str)
    status = Signal(str)             # informational message
    error = Signal(str)              # error message (popup)
    device_ready = Signal(str)       # device hostname
    prompt_changed = Signal(str)     # e.g. P1234567@sw01>
    secret_requested = Signal(str)   # device wants a password -> UI calls send_secret()
    busy_changed = Signal(bool)

    _raw = Signal(int, str)
    _connected = Signal(bool, str)
    _closed = Signal(int)
    _bastion_up = Signal(int)
    _need_secret = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = None
        self.bastion_client = None
        self.chan = None
        self._awaiting_device = False
        self.state = DISCONNECTED
        self.params = {}
        self.queue = deque()
        self.job = None
        self.device_host = ""
        self.prompt = ""
        self._tail = ""
        self._hop_sent = False
        self._pw_count = 0
        self._stop = False
        self._gen = 0

        self._raw.connect(self._on_raw)
        self._connected.connect(self._on_connected)
        self._closed.connect(self._on_closed)
        self._bastion_up.connect(self._on_bastion_up)
        self._need_secret.connect(self._on_need_secret)

        self._job_timer = QTimer(self)
        self._job_timer.setSingleShot(True)
        self._job_timer.timeout.connect(self._on_job_timeout)
        self._hop_timer = QTimer(self)
        self._hop_timer.setSingleShot(True)
        self._hop_timer.timeout.connect(self._send_hop)

    # ================================================================ connect
    def connect_to(self, bastion, username, password, token, hostname, *, mode="jump",
                   device_username="", device_password="", device_domain="",
                   hop_template="ssh {hostname}", login_template="{username}",
                   switch_auth="password", command_timeout=180):
        """mode='jump'  : SSH tunnel through the jump host straight to the switch (direct-tcpip).
           mode='shell' : open a shell on the bastion and type the hop command."""
        if self.state != DISCONNECTED:
            self.close_session()
        hpart, _, port_s = hostname.strip().partition(":")
        dom = (device_domain or "").strip().lstrip(".")
        if dom and "." not in hpart and not re.fullmatch(r"[\d.]+", hpart):
            hpart = f"{hpart}.{dom}"
        dev_user = (device_username or "").strip() or username
        dev_pw = device_password or password
        fill = lambda t, u: (t or "").replace("{username}", u).replace("{hostname}", hpart)
        self.params = {
            "mode": mode, "bastion": bastion.strip(), "username": username, "password": password,
            "secret": password + token, "hostname": hostname.strip(), "target": hpart,
            "target_port": int(port_s) if port_s.isdigit() else 22,
            "dev_user": dev_user, "dev_password": dev_pw,
            "login": fill(login_template, username) or username, "hop": fill(hop_template, dev_user).strip(),
            "switch_auth": switch_auth, "timeout": int(command_timeout or 180),
        }
        self._awaiting_device = False
        self._gen += 1
        self._set_state(CONNECTING)
        self.status.emit(f"Connecting to jump host {self.params['bastion']} as {self.params['login']}…")
        threading.Thread(target=self._connect_worker, args=(self._gen,), daemon=True).start()

    @staticmethod
    def _new_client():
        import paramiko
        c = paramiko.SSHClient()
        try:
            c.load_system_host_keys()
        except Exception:
            pass
        try:
            KNOWN_HOSTS.parent.mkdir(parents=True, exist_ok=True)
            KNOWN_HOSTS.touch(exist_ok=True)
            c.load_host_keys(str(KNOWN_HOSTS))
        except Exception:
            pass
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return c

    @staticmethod
    def _save_keys(c):
        try:
            c.save_host_keys(str(KNOWN_HOSTS))
        except Exception:
            pass

    def _start_reader(self, client, chan, gen):
        chan.settimeout(0.5)
        self.client, self.chan = client, chan
        self._stop = False
        threading.Thread(target=self._reader, args=(chan, gen), daemon=True).start()

    def _connect_worker(self, gen):
        import paramiko
        p = self.params
        host, port = p["bastion"], 22
        if host.count(":") == 1:
            host, _, port_s = host.partition(":")
            port = int(port_s or 22)
        try:
            client = self._new_client()
            client.connect(host, port=port, username=p["login"], password=p["secret"],
                           look_for_keys=False, allow_agent=False,
                           timeout=20, banner_timeout=30, auth_timeout=60)
            self._save_keys(client)
            if gen != self._gen:          # user cancelled / reconnected meanwhile
                client.close()
                return
            self.bastion_client = client
            if p["mode"] == "shell":
                chan = client.invoke_shell(term="vt100", width=400, height=10000)
                self._start_reader(client, chan, gen)
                self._connected.emit(True, "shell")
                return
            self._bastion_up.emit(gen)
            if p["switch_auth"] == "password_vip":
                # Only ask for a code now if tunnels are allowed; otherwise the shell path asks later.
                try:
                    probe = client.get_transport().open_channel(
                        "direct-tcpip", (p["target"], p["target_port"]), ("127.0.0.1", 0), timeout=20)
                    probe.close()
                except paramiko.ChannelException:
                    self._device_worker(gen, p["dev_password"])   # falls back to the bastion shell
                    return
                self._need_secret.emit(gen, f"{p['target']} needs your password + a new VIP code.")
            else:
                self._device_worker(gen, p["dev_password"])
        except paramiko.AuthenticationException:
            self._connected.emit(False, "Jump host authentication failed.\n\nCheck your P-Number and password, "
                                        "and use a fresh VIP token (they change every 30 seconds).\n"
                                        "If the jump host needs a domain prefix (e.g. DOMAIN\\P1234567), set "
                                        "'Jump host login name' in Settings.")
        except socket.gaierror:
            self._connected.emit(False, f"Could not resolve jump host '{host}'.")
        except (socket.timeout, TimeoutError):
            self._connected.emit(False, f"Timed out connecting to jump host {host}:{port}.")
        except Exception as e:  # noqa: BLE001
            self._connected.emit(False, f"Jump host connection failed: {type(e).__name__}: {e}")

    def _device_worker(self, gen, secret):
        """Open a direct-tcpip tunnel through the jump host and log in to the switch."""
        import paramiko
        p = self.params
        target, tport = p["target"], p["target_port"]
        try:
            tr = self.bastion_client.get_transport() if self.bastion_client else None
            if tr is None or not tr.is_active():
                raise paramiko.SSHException("jump host session is closed")
            sock = tr.open_channel("direct-tcpip", (target, tport), ("127.0.0.1", 0), timeout=20)
            dev = self._new_client()
            dev.connect(target, port=tport, username=p["dev_user"], password=secret, sock=sock,
                        look_for_keys=False, allow_agent=False, timeout=20, banner_timeout=30, auth_timeout=60)
            self._save_keys(dev)
            chan = dev.invoke_shell(term="vt100", width=400, height=10000)
            if gen != self._gen:
                dev.close()
                return
            self._start_reader(dev, chan, gen)
            self._connected.emit(True, "jump")
        except paramiko.AuthenticationException:
            self._need_secret.emit(gen, f"{target} rejected the login for {p['dev_user']}.")
        except paramiko.ChannelException as e:
            # Jump host refuses tunnels (e.g. "Administratively prohibited") -> use its shell instead,
            # on the same login, and type "ssh <switch>" like you would in PuTTY.
            try:
                chan = self.bastion_client.invoke_shell(term="vt100", width=400, height=10000)
                if gen != self._gen:
                    return
                self._start_reader(self.bastion_client, chan, gen)
                self.status.emit("Jump host does not allow tunnels – using its shell to reach the switch…")
                self._connected.emit(True, "shell")
            except Exception as e2:  # noqa: BLE001
                self._connected.emit(False, f"The jump host could not reach {target}:{tport} ({e}) and its "
                                            f"shell could not be opened ({e2}).")
        except Exception as e:  # noqa: BLE001
            self._connected.emit(False, f"Connection to {target} through the jump host failed: "
                                        f"{type(e).__name__}: {e}")

    def _reader(self, chan, gen):
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        while not self._stop:
            try:
                data = chan.recv(65535)
            except socket.timeout:
                continue
            except Exception:
                break
            if not data:
                break
            self._raw.emit(gen, dec.decode(data))
        self._closed.emit(gen)

    def _on_bastion_up(self, gen):
        if gen == self._gen and self.state == CONNECTING:
            self._set_state(HOPPING)
            self.status.emit(f"Jump host connected – opening tunnel to {self.params['target']}…")

    def _on_need_secret(self, gen, msg):
        if gen != self._gen or self.state == DISCONNECTED:
            return
        self._awaiting_device = True
        self.secret_requested.emit(msg)

    def _on_connected(self, ok: bool, how: str):
        if self.state not in (CONNECTING, HOPPING):
            return
        if not ok:
            self.close_session()
            self.error.emit(how)
            return
        self._tail = ""
        self._pw_count = 0
        self._set_state(HOPPING)
        if how == "jump":
            self._hop_sent = True       # nothing to type – we are already on the switch
            self.status.emit(f"Logged in to {self.params['target']} – waiting for the Junos prompt…")
        else:
            self._hop_sent = False
            self.status.emit(f"Bastion connected – reaching {self.params['target']}…")
            self._hop_timer.start(6000)

    # ================================================================ data in
    def _on_raw(self, gen: int, text: str):
        if gen != self._gen:
            return
        text = clean_text(text)
        if not text:
            return
        if self.state == HOPPING:
            self.console.emit(text)
            self._tail = (self._tail + text)[-3000:]
            self._handle_hop()
            return
        if self.state != READY:
            self.console.emit(text)
            return
        job = self.job
        if job is None:
            self.console.emit(text)
            self._tail = (self._tail + text)[-3000:]
            pr = find_prompt(self._tail)
            if pr:
                self._update_prompt(pr)
            return
        job.buffer += text
        if not job.background:
            self.console.emit(text)
        if not job.help_query:
            pr = find_prompt(job.buffer)
            if pr:
                self._update_prompt(pr)
                self._finish_job()

    def _handle_hop(self):
        t = self._tail
        p = self.params
        pr = find_prompt(t)
        if pr:
            self._become_ready(pr)
            return
        if _YESNO_RE.search(t):
            self._tail = ""
            self._send_raw("yes\n")
            return
        if _LOGIN_RE.search(t):
            self._tail = ""
            self._send_raw(p["username"] + "\n")
            return
        if _PASS_RE.search(t):
            self._tail = ""
            self._pw_count += 1
            if self._pw_count == 1 and p["switch_auth"] == "password":
                self._send_raw(p["dev_password"] + "\n")
                self.status.emit("Password sent to device…")
            else:
                again = " again" if self._pw_count > 1 else ""
                last = t.strip().splitlines()[-1].strip() if t.strip() else "Password:"
                self.secret_requested.emit(f"{p['hostname'] or 'The device'} is asking{again}: “{last[-60:]}”.")
            return
        m = _FAIL_RE.search(t[-400:])
        if m:
            self.status.emit(f"Bastion reported: {m.group(1)}")
        if not self._hop_sent and _SHELL_RE.search(t):
            self._send_hop()

    def _send_hop(self):
        if self.state != HOPPING or self._hop_sent:
            return
        self._hop_sent = True
        hop = self.params.get("hop", "")
        if not hop:
            self.status.emit("Bastion connected – type in the CLI to reach your device.")
            return
        self._send_raw(hop + "\n")

    def _become_ready(self, pr):
        self._hop_timer.stop()
        self._tail = ""
        self._update_prompt(pr)
        self.device_host = pr[1]
        self._set_state(READY)
        self.device_ready.emit(self.device_host)
        self.status.emit(f"Connected to {self.device_host}")
        for c in ("set cli screen-length 0", "set cli screen-width 0", "set cli complete-on-space off"):
            self.enqueue(c, background=True, timeout=20)

    def _update_prompt(self, pr):
        prompt = f"{pr[0]}@{pr[1]}{pr[2]}"
        if prompt != self.prompt:
            self.prompt = prompt
            self.prompt_changed.emit(prompt)

    # ================================================================ data out
    def _send_raw(self, text: str):
        try:
            if self.chan is not None:
                self.chan.send(text)
        except Exception as e:  # noqa: BLE001
            self.error.emit(f"Send failed: {e}")

    def send_token(self, token: str):
        """Answer a password request with the device password + VIP token (token may be blank)."""
        secret = self.params.get("dev_password", "") + (token or "")
        if self._awaiting_device:
            self._awaiting_device = False
            self.status.emit(f"Retrying login to {self.params['target']}…")
            threading.Thread(target=self._device_worker, args=(self._gen, secret), daemon=True).start()
        else:
            self._send_raw(secret + "\n")

    def cancel_token(self):
        if self._awaiting_device:
            self._awaiting_device = False
            self.status.emit("Login cancelled.")
            self.close_session()

    def send_user_line(self, line: str):
        """A line typed into the CLI."""
        if self.state in (HOPPING, CONNECTING):
            self._send_raw(line + "\n")
            return
        if self.state != READY:
            self.error.emit("Not connected.")
            return
        if line.strip().lower() in EXIT_WORDS and self.prompt.endswith(">"):
            self._send_raw(line + "\n")
            self._set_state(HOPPING)
            self._hop_sent = True
            self._pw_count = 0
            self.prompt = ""
            self.prompt_changed.emit("")
            self.status.emit("Left the device – back on the bastion.")
            return
        if line.rstrip().endswith("?"):
            self.enqueue(line.rstrip(), help_query=True, timeout=2)
        else:
            self.enqueue(line)

    def interrupt(self):
        self._send_raw("\x03")

    def enqueue(self, command, background=False, callback=None, tag=None, timeout=None, help_query=False):
        if self.state != READY:
            return None
        job = Job(command, background, callback, tag, timeout or self.params.get("timeout", 180), help_query)
        self.queue.append(job)
        self._pump()
        return job

    def pending_tags(self):
        tags = {j.tag for j in self.queue if j.tag}
        if self.job and self.job.tag:
            tags.add(self.job.tag)
        return tags

    def _pump(self):
        if self.job is not None or not self.queue or self.state != READY:
            return
        job = self.queue.popleft()
        self.job = job
        job.started = time.time()
        self.busy_changed.emit(True)
        if job.help_query:
            self._send_raw(job.command)
            self._job_timer.start(1500)
        else:
            self._send_raw(job.command + "\n")
            self._job_timer.start(int(job.timeout * 1000))

    def _on_job_timeout(self):
        job = self.job
        if job is None:
            return
        if job.help_query:
            self._send_raw("\x15")      # Ctrl-U: clear the partially typed line
        else:
            job.timed_out = True
            if job.background:
                self._send_raw("\x03")
            self.status.emit(f"Command timed out: {job.command[:60]}")
        self._finish_job()

    def _finish_job(self):
        job = self.job
        self.job = None
        self._job_timer.stop()
        if job is None:
            return
        job.output = strip_command_output(job.buffer, job.command)
        if job.callback:
            try:
                job.callback(job)
            except Exception as e:  # noqa: BLE001
                self.status.emit(f"Error processing '{job.command[:40]}': {e}")
        if not self.queue:
            self.busy_changed.emit(False)
        QTimer.singleShot(0, self._pump)

    # ================================================================ close
    def close_session(self):
        self._stop = True
        self._gen += 1
        self._hop_timer.stop()
        self._job_timer.stop()
        self.queue.clear()
        self.job = None
        try:
            if self.chan is not None:
                self.chan.close()
        except Exception:
            pass
        for c in (self.client, self.bastion_client):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass
        self.chan = None
        self.client = None
        self.bastion_client = None
        self._awaiting_device = False
        self.device_host = ""
        self.prompt = ""
        self.prompt_changed.emit("")
        self.busy_changed.emit(False)
        self._set_state(DISCONNECTED)

    def _on_closed(self, gen: int):
        if gen == self._gen and self.state != DISCONNECTED:
            self.status.emit("Session closed by remote host.")
            self.close_session()

    def _set_state(self, st):
        if st != self.state:
            self.state = st
            self.state_changed.emit(st)

    @property
    def is_ready(self):
        return self.state == READY
