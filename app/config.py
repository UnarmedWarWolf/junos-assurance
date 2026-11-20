"""Persistent settings and password cache.

Settings file:  Windows  %APPDATA%\\JunosAssurance\\config.json
                macOS    ~/.junos_assurance/config.json

The password is stored in the operating-system keychain via `keyring`
(macOS Keychain / Windows Credential Manager). It is never written to the
JSON file. If keyring is unavailable the password is cached for the
current session only.
"""
import json
import os
import sys
from pathlib import Path

from .parsers import MONITOR_COMMANDS

APP_NAME = "Junos Assurance"
if sys.platform == "win32" and os.environ.get("APPDATA"):
    APP_DIR = Path(os.environ["APPDATA"]) / "JunosAssurance"      # C:\Users\<you>\AppData\Roaming
else:
    APP_DIR = Path.home() / ".junos_assurance"
CONFIG_FILE = APP_DIR / "config.json"
KNOWN_HOSTS = APP_DIR / "known_hosts"
KEYRING_SERVICE = "JunosAssurance"

DEFAULTS = {
    "bastion": "",
    "username": "",
    # "jump": tunnel through the jump host straight to the switch (ssh -J style)
    # "shell": log in to a shell on the bastion and type the hop command
    "connection_mode": "jump",
    # Appended to switch names without a dot, e.g. "net.example.com" -> qfx-01.net.example.com
    "device_domain": "",
    # Separate switch credentials (when the switches use a different domain/account than the jump host)
    "use_device_creds": False,
    "device_username": "",
    "remember_password": True,
    "recent_hosts": [],
    # Command sent on the bastion to reach the switch. {username} and {hostname} are filled in.
    # Leave blank if your bastion logs you straight into the device (e.g. user@host@bastion style).
    "hop_template": "ssh {hostname}",
    # Jump host login name. e.g. "{username}", "DOMAIN\\{username}" or "{username}@jumpdomain.com"
    "bastion_login_template": "{username}",
    # What to answer when the switch asks for a password:
    #   password      -> saved password only
    #   password_vip  -> ask for a fresh VIP token and send password+token
    "switch_auth": "password",
    "monitor_enabled": True,
    "poll_interval": 120,
    "flap_window_hours": 24,
    "rx_warn_default": -12.0,
    "rx_alarm_default": -15.0,
    "monitor_commands": dict(MONITOR_COMMANDS),
    "last_save_dir": str(Path.home()),
    "window_geometry": "",
    "command_timeout": 180,
}


class Config:
    def __init__(self):
        self.data = json.loads(json.dumps(DEFAULTS))
        self._session_password = {}
        self.load()

    def load(self):
        try:
            if CONFIG_FILE.exists():
                stored = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                for k, v in stored.items():
                    if k == "monitor_commands" and isinstance(v, dict):
                        self.data[k].update(v)
                    else:
                        self.data[k] = v
            # migrate the old default hop command – the bastion already knows who you are
            if self.data.get("hop_template") == "ssh {username}@{hostname}":
                self.data["hop_template"] = "ssh {hostname}"
            self.data["switch_auth"] = self.data.get("switch_auth") or "password"
        except Exception:
            pass

    def save(self):
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def __getitem__(self, k):
        return self.data.get(k, DEFAULTS.get(k))

    def __setitem__(self, k, v):
        self.data[k] = v

    def add_recent_host(self, host: str):
        host = host.strip()
        if not host:
            return
        hosts = [h for h in self.data.get("recent_hosts", []) if h.lower() != host.lower()]
        self.data["recent_hosts"] = [host] + hosts[:24]

    # ------------------------------------------------------------ password
    # Switch passwords are stored under a separate keychain entry
    def get_device_password(self, username: str) -> str:
        return self.get_password("device::" + username) if username else ""

    def set_device_password(self, username: str, password: str, persist: bool = True):
        if username:
            self.set_password("device::" + username, password, persist)

    def get_password(self, username: str) -> str:
        if not username:
            return ""
        if username in self._session_password:
            return self._session_password[username]
        try:
            import keyring
            return keyring.get_password(KEYRING_SERVICE, username) or ""
        except Exception:
            return ""

    def set_password(self, username: str, password: str, persist: bool = True):
        if not username:
            return
        self._session_password[username] = password
        if not persist:
            self.delete_password(username, keep_session=True)
            return
        try:
            import keyring
            keyring.set_password(KEYRING_SERVICE, username, password)
        except Exception:
            pass

    def delete_password(self, username: str, keep_session: bool = False):
        if not keep_session:
            self._session_password.pop(username, None)
        try:
            import keyring
            keyring.delete_password(KEYRING_SERVICE, username)
        except Exception:
            pass

    @staticmethod
    def keyring_available() -> bool:
        try:
            import keyring
            kr = keyring.get_keyring()
            return "fail" not in type(kr).__module__.lower()
        except Exception:
            return False
