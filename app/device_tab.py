"""One switch session = one tab: dashboard, port map, tables, CLI, automation output, Interface 360."""
import os
import re
import time
from datetime import datetime

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QScrollArea, QSplitter, QVBoxLayout, QWidget)

from . import exporters
from .commands import CATALOG, render
from .dialogs import ExplainDialog, PlaybookDialog, SnapshotDiffDialog, SnapshotsDialog
from .history import diff_snapshots
from .parsers import (HEALTH_ORDER, evaluate_optics, fmt_age, parse_descriptions, parse_extensive, parse_flaps,
                      parse_lldp, parse_optics, parse_terse, split_port)
from .playbooks import PLAYBOOKS, get_playbook
from .portmap import STATE_LABEL, InterfacePanel, PortMapWidget, legend_widget
from .session_log import SessionLogger, default_log_dir
from .ssh_session import CONNECTING, DISCONNECTED, HOPPING, READY, JunosSession
from .theme import COLORS
from .widgets import (Card, CliConsole, DashletTable, HealthRing, InterfacePickDialog, KpiTile, OutputPanel,
                      ParamDialog, VipDialog, health_word)


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


class DeviceTab(QWidget):
    alert = Signal(str, str, str)          # title, message, color key
    health_changed = Signal(object)        # int score or None
    state_changed = Signal(str)
    status = Signal(str)
    title_changed = Signal(str)

    def __init__(self, cfg, history, inventory, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.cfg, self.history, self.inventory = cfg, history, inventory
        self.session = JunosSession(self)
        self.host = ""                 # hostname as typed
        self.jump = ""
        self.user = ""
        self.logger = None
        self.terse, self.desc, self.flaps, self.optics = {}, {}, [], {}
        self.prev_flap, self.session_flaps = {}, {}
        self.trends = {}
        self.score = None
        self.last_auto = None          # (name, command, output)
        self.last_output = None        # (command, output) of the last CLI command
        self.last_refresh = None
        self.selected_iface = None
        self._after_refresh = []
        self._baseline = False
        self._prev_terse, self._prev_health = {}, {}
        self._trend_alerted = set()
        self._dash_host = None
        self.paused = False

        self._build()
        self._wire()
        self.mon_timer = QTimer(self)
        self.mon_timer.timeout.connect(self.run_monitor_cycle)

    # ============================================================== layout
    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setHandleWidth(8)
        outer.addWidget(self.split)

        content = QWidget()
        content.setObjectName("Page")
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        self.ring = HealthRing()
        kpis.addWidget(self.ring)
        self.k_up = KpiTile("Ports Up", "physical ports")
        self.k_down = KpiTile("Admin Up · Link Down", "enabled ports without link")
        self.k_flap = KpiTile("Recent Flaps", "")
        self.k_optics = KpiTile("Optics Health", "")
        for k in (self.k_up, self.k_down, self.k_flap, self.k_optics):
            kpis.addWidget(k, 1)
        col.addLayout(kpis)

        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.setHandleWidth(10)
        pm = Card("Port Map")
        pm.add_title_widget(legend_widget())
        self.portmap = PortMapWidget()
        pm_scroll = QScrollArea()
        pm_scroll.setObjectName("PanelScroll")
        pm_scroll.setWidgetResizable(True)
        pm_scroll.setFrameShape(QFrame.Shape.NoFrame)
        pm_scroll.setWidget(self.portmap)
        hint = QLabel("Click a port for Interface 360")
        hint.setObjectName("Muted")
        pm.body.addWidget(pm_scroll, 1)
        pm.body.addWidget(hint)
        pm.outer.setContentsMargins(14, 10, 14, 8)

        top = QSplitter(Qt.Orientation.Horizontal)
        top.setHandleWidth(10)
        self.t_flaps = DashletTable("Flap List", ["Interface", "Description", "Link", "Severity",
                                                  "Last Flapped", "Age", "Seen"], "No recent flaps")
        self.t_down = DashletTable("Admin Up · Link Down", ["Interface", "Description", "Admin", "Link"],
                                   "All enabled ports have link")
        self.t_optics = DashletTable("Port Health (Optics)", ["Interface", "Description", "Health", "Rx dBm",
                                                              "Tx dBm", "Rx trend", "Detail"],
                                     "No optic readings yet")
        for t in (self.t_flaps, self.t_down, self.t_optics):
            top.addWidget(t)
        top.setSizes([430, 360, 520])

        bottom = QSplitter(Qt.Orientation.Horizontal)
        bottom.setHandleWidth(10)
        self.cli = CliConsole()
        self.cli.input.add_phrases(c.template.split("|")[0].split("[[")[0].split("{")[0] for c in CATALOG)
        self.auto_card = Card("Automation Output")
        self.auto_panel = OutputPanel()
        self.auto_card.add_title_widget(self.auto_panel.filter_edit)
        b_explain = QPushButton("Explain")
        b_explain.setToolTip("Explain this output in plain English")
        b_explain.clicked.connect(self.explain_auto)
        b_again = QPushButton("Run again")
        b_again.clicked.connect(self._rerun_auto)
        b_save = QPushButton("Save to Excel…")
        b_save.clicked.connect(self.save_auto_output)
        for b in (b_explain, b_again, b_save):
            self.auto_card.add_title_widget(b)
        self.auto_cmd_label = QLabel("Choose a command from Commands in the left menu")
        self.auto_cmd_label.setObjectName("Muted")
        self.auto_cmd_label.setWordWrap(True)
        box = QFrame()
        box.setObjectName("Boxed")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.auto_panel)
        self.auto_card.body.addWidget(self.auto_cmd_label)
        self.auto_card.body.addWidget(box, 1)
        self.auto_card.outer.setContentsMargins(10, 10, 10, 10)
        bottom.addWidget(self.cli)
        bottom.addWidget(self.auto_card)
        bottom.setSizes([820, 470])

        vsplit.addWidget(pm)
        vsplit.addWidget(top)
        vsplit.addWidget(bottom)
        vsplit.setSizes([170, 270, 430])
        col.addWidget(vsplit, 1)

        self.detail = InterfacePanel()
        self.detail.hide()
        self.split.addWidget(content)
        self.split.addWidget(self.detail)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)

    def _wire(self):
        s = self.session
        s.console.connect(self._console)
        s.state_changed.connect(self._on_state)
        s.status.connect(self.status.emit)
        s.error.connect(lambda m: QMessageBox.warning(self, "Junos Assurance", m))
        s.device_ready.connect(self._on_device_ready)
        s.prompt_changed.connect(self.cli.set_prompt)
        s.secret_requested.connect(self._on_secret_requested)
        self.cli.command_entered.connect(self.send_cli_line)
        self.cli.ctrl_c.connect(lambda: self.session.interrupt())
        self.cli.save_requested.connect(self.save_cli)
        self.cli.explain_requested.connect(self.explain_last)
        self.portmap.port_clicked.connect(self.open_interface)
        for t in (self.t_flaps, self.t_down, self.t_optics):
            t.row_activated.connect(self.open_interface)
        self.detail.close_requested.connect(self.close_interface)
        self.detail.refresh_requested.connect(self._refresh_interface)
        self.detail.run_command.connect(self.send_cli_line)
        self.detail.run_playbook.connect(self.run_playbook)

    # ============================================================== naming
    @property
    def device_name(self):
        return self.session.device_host or self.host

    @property
    def state(self):
        return self.session.state

    @property
    def is_ready(self):
        return self.session.is_ready

    # ============================================================== connect
    def connect_device(self, jump, user, password, token, host, dev_user="", dev_password=""):
        c = self.cfg
        self.host, self.jump, self.user = host, jump, user
        self.title_changed.emit(host)
        self._reset_dashboard()
        if self.logger:
            self.logger.close()
        self.logger = SessionLogger(c["log_dir"] or default_log_dir(), host, user, jump) \
            if c["session_logging"] else None
        self._console(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S}  Connecting to {host} via jump host "
                      f"{jump} as {user} =====\n")
        self.session.connect_to(jump, user, password, token, host, mode=c["connection_mode"],
                                device_username=dev_user, device_password=dev_password,
                                device_domain=c["device_domain"], hop_template=c["hop_template"],
                                login_template=c["bastion_login_template"], switch_auth=c["switch_auth"],
                                command_timeout=c["command_timeout"])

    def disconnect_device(self):
        self.session.close_session()

    def shutdown(self):
        self.mon_timer.stop()
        self.session.close_session()
        if self.logger:
            self.logger.close()
            self.logger = None

    def _console(self, text):
        self.cli.append(text)
        if self.logger:
            self.logger.write(text)

    def _on_secret_requested(self, msg):
        dlg = VipDialog(self, message=msg + " Enter a new VIP code to send your switch password + code, "
                                            "or leave it blank to send just the password.", allow_empty=True)
        if dlg.exec():
            self.session.send_token(dlg.value())
        else:
            self.session.cancel_token()

    def _on_state(self, st):
        if st in (DISCONNECTED, HOPPING):
            self.mon_timer.stop()
        self.state_changed.emit(st)

    def _on_device_ready(self, host):
        if host != self._dash_host:
            self._reset_dashboard()
            self._dash_host = host
        self.title_changed.emit(host)
        self.inventory.touch(self.host)
        try:
            self.history.prune(int(self.cfg["history_days"]))
        except Exception:
            pass
        QTimer.singleShot(500, self.run_monitor_cycle)
        self.restart_timer()

    def restart_timer(self, paused=False):
        self.mon_timer.stop()
        self.paused = paused
        if self.cfg["monitor_enabled"] and not paused and self.is_ready:
            self.mon_timer.start(int(self.cfg["poll_interval"]) * 1000)

    # ============================================================== CLI
    def send_cli_line(self, line):
        if self.session.state == DISCONNECTED:
            self._console("\n% Not connected. Enter your details in Connect and press Connect.\n")
            return
        if self.logger:
            self.logger.mark(line)
        self.session.send_user_line(line, callback=self._user_done)

    def _user_done(self, job):
        self.last_output = (job.command, job.output)

    def explain_last(self):
        if not self.last_output:
            QMessageBox.information(self, "Explain", "Run a command in the CLI first. Its output will be explained.")
            return
        ExplainDialog(self.last_output[1], f"Explain: {self.last_output[0]}", self).show()

    def explain_auto(self):
        if not self.last_auto or not self.last_auto[2]:
            QMessageBox.information(self, "Explain", "Run an automation command first.")
            return
        ExplainDialog(self.last_auto[2], f"Explain: {self.last_auto[1]}", self).show()

    # ============================================================== automation
    def all_interfaces(self):
        names = set(self.terse) | set(self.optics) | {f["interface"] for f in self.flaps} | set(self.desc)
        return sorted(names, key=natural_key)

    def run_automation(self, cmd):
        if not self.is_ready:
            QMessageBox.information(self, "Junos Assurance", "Connect to a switch first.")
            return
        values = {}
        if cmd.params:
            dlg = ParamDialog(cmd, self.all_interfaces(), self,
                              preset={"interface": self.selected_iface or ""})
            if not dlg.exec():
                return
            values = dlg.values()
        try:
            command = render(cmd, values)
        except ValueError as e:
            QMessageBox.warning(self, "Junos Assurance", str(e))
            return
        self._run_auto_command(cmd.name, command)

    def _run_auto_command(self, name, command):
        self.auto_card.title_label.setText(f"Automation Output — {name}")
        self.auto_cmd_label.setText(f"› {command}")
        self.auto_panel.setPlainText(f"Running on {self.device_name}…")
        self.last_auto = (name, command, None)
        if self.logger:
            self.logger.mark(command)
        self.session.enqueue(command, callback=lambda job, n=name: self._auto_done(n, job), tag="auto")

    def _auto_done(self, name, job):
        out = job.output + ("\n\n% Command timed out – output may be incomplete." if job.timed_out else "")
        self.auto_panel.setPlainText(out)
        self.last_auto = (name, job.command, out)
        self.last_output = (job.command, out)
        self.status.emit(f"'{name}' finished – {len(out.splitlines())} lines")

    def _rerun_auto(self):
        if self.last_auto and self.is_ready:
            self._run_auto_command(self.last_auto[0], self.last_auto[1])

    # ============================================================== playbooks
    def run_playbook(self, key, iface=None):
        pb = get_playbook(key)
        if not self.is_ready:
            QMessageBox.information(self, pb.name, "Connect to a switch first.")
            return
        if not iface:
            dlg = InterfacePickDialog(pb.name, pb.description, self.all_interfaces(), self,
                                      preset=self.selected_iface or "")
            if not dlg.exec():
                return
            iface = dlg.value()
        PlaybookDialog(pb, iface, self.session.enqueue, self.device_name,
                       float(self.cfg["rx_warn_default"]), float(self.cfg["rx_alarm_default"]), self).show()

    # ============================================================== monitoring
    def run_monitor_cycle(self, force=False):
        s = self.session
        if not s.is_ready or "mon" in s.pending_tags():
            return
        mc = self.cfg["monitor_commands"]
        s.enqueue(mc["terse"], background=True, tag="mon", callback=self._got_terse)
        s.enqueue(mc["descriptions"], background=True, tag="mon", callback=self._got_desc)
        s.enqueue(mc["flaps"], background=True, tag="mon", callback=self._got_flaps)
        s.enqueue(mc["optics"], background=True, tag="mon", callback=self._got_optics)

    def refresh_then(self, callback):
        """Run a fresh health refresh, then call callback() once the data is in."""
        if not self.is_ready:
            QMessageBox.information(self, "Junos Assurance", "Connect to a switch first.")
            return
        self._after_refresh.append(callback)
        self.run_monitor_cycle(force=True)

    def _got_terse(self, job):
        parsed = parse_terse(job.output)
        if parsed or not job.timed_out:
            self.terse = parsed
        self._refresh_dashboard()

    def _got_desc(self, job):
        self.desc = parse_descriptions(job.output)
        self._refresh_dashboard()

    def _got_flaps(self, job):
        rows = parse_flaps(job.output)
        for r in rows:
            name, lf = r["interface"], r["last_flapped"]
            prev = self.prev_flap.get(name)
            if prev is not None and lf != prev and lf != "Never":
                self.session_flaps[name] = self.session_flaps.get(name, 0) + 1
                d = self.desc.get(name, "")
                self.alert.emit(f"{self.device_name}: {name} flapped",
                                f"{name}{' (' + d + ')' if d else ''} flapped at {lf}", "warning")
            self.prev_flap[name] = lf
        self.flaps = rows
        self._refresh_dashboard()

    def _got_optics(self, job):
        self.optics = parse_optics(job.output)
        self.last_refresh = time.time()
        dev = self.device_name
        samples = {}
        for n, e in self.optics.items():
            if e["rx"] or e["tx"]:
                samples[n] = (min(e["rx"]) if e["rx"] else None, min(e["tx"]) if e["tx"] else None)
        try:
            self.history.record_optics(dev, samples)
            self.trends = self.history.trends(dev, float(self.cfg["trend_hours"]))
        except Exception:
            self.trends = {}
        self._refresh_dashboard()
        self._detect_alerts()
        cbs, self._after_refresh = self._after_refresh, []
        for cb in cbs:
            try:
                cb()
            except Exception as e:  # noqa: BLE001
                self.status.emit(f"Error: {e}")

    def _detect_alerts(self):
        health = {}
        for n, e in self.optics.items():
            health[n] = evaluate_optics(e, float(self.cfg["rx_warn_default"]), float(self.cfg["rx_alarm_default"]))[0]
        if self._baseline:
            dev = self.device_name
            for n, v in self.terse.items():
                p = self._prev_terse.get(n)
                if p and p["link"] == "up" and v["link"] == "down" and v["admin"] == "up":
                    d = self.desc.get(n, "")
                    self.alert.emit(f"{dev}: {n} went DOWN", f"{n}{' (' + d + ')' if d else ''} lost link.", "down")
            bad = ("Warning", "Critical", "No Light")
            for n, h in health.items():
                if h in bad and self._prev_health.get(n) == "OK" and self.terse.get(n, {}).get("link") != "down":
                    self.alert.emit(f"{dev}: {n} optics {h}", f"Receive light on {n} is now {h.lower()}.",
                                    "down" if h != "Warning" else "warning")
            limit = float(self.cfg["trend_alert_db"])
            for n, (first, last, delta, cnt) in self.trends.items():
                if cnt >= 3 and delta <= -limit and n not in self._trend_alerted \
                        and self.terse.get(n, {}).get("link") != "down":
                    self._trend_alerted.add(n)
                    self.alert.emit(f"{dev}: light on {n} is degrading",
                                    f"Rx dropped {abs(delta):.1f} dB in {self.cfg['trend_hours']} h "
                                    f"({first:.2f} → {last:.2f} dBm). Clean or check the fiber before it fails.",
                                    "warning")
        self._prev_terse = {n: dict(v) for n, v in self.terse.items()}
        self._prev_health = health
        self._baseline = True

    def refresh_text(self):
        if not self.is_ready:
            return "Not connected"
        if "mon" in self.session.pending_tags():
            return "Refreshing health data…"
        parts = []
        if self.last_refresh:
            parts.append(f"Last refresh {datetime.fromtimestamp(self.last_refresh):%H:%M:%S}")
        if getattr(self, "paused", False) or not self.cfg["monitor_enabled"]:
            parts.append("background checks paused")
        elif self.mon_timer.isActive():
            parts.append(f"next in {max(0, self.mon_timer.remainingTime() // 1000)} s")
        return " · ".join(parts) or "Waiting…"

    def _reset_dashboard(self):
        self.close_interface()
        self.terse, self.desc, self.flaps, self.optics = {}, {}, [], {}
        self.prev_flap, self.session_flaps, self.trends = {}, {}, {}
        self._baseline, self._prev_terse, self._prev_health = False, {}, {}
        self._trend_alerted = set()
        self.last_refresh = None
        self._refresh_dashboard()

    # ============================================================== dashboard
    def _dashboard_rows(self):
        window = int(self.cfg["flap_window_hours"]) * 3600
        flap_rows = []
        age_of = {}
        for f in self.flaps:
            age, seen = f["age"], self.session_flaps.get(f["interface"], 0)
            if (age is None or age > window) and not seen:
                continue
            age_of[f["interface"]] = age or 0
            sev = "Critical" if (age is not None and age < 3600) else "Warning"
            flap_rows.append([f["interface"], self.desc.get(f["interface"], ""), f["link"].capitalize(), sev,
                              f["last_flapped"], fmt_age(age), seen or ""])
        flap_rows.sort(key=lambda r: age_of.get(r[0], 0))
        down_rows = [[n, self.desc.get(n, ""), "Up", "Down"]
                     for n, v in self.terse.items() if v["admin"] == "up" and v["link"] == "down"]
        down_rows.sort(key=lambda r: natural_key(r[0]))
        opt_rows = []
        limit = float(self.cfg["trend_alert_db"])
        for n, entry in self.optics.items():
            health, worst, reason = evaluate_optics(entry, float(self.cfg["rx_warn_default"]),
                                                    float(self.cfg["rx_alarm_default"]))
            tx = min(entry["tx"]) if entry["tx"] else None
            tr = self.trends.get(n)
            if tr and tr[3] >= 2:
                d = tr[2]
                arrow = "▼" if d < 0 else ("▲" if d > 0 else "▶")
                key = "down" if d <= -limit else ("warning" if d <= -limit / 2 else None)
                trend = (f"{arrow} {abs(d):.1f} dB", key)
            else:
                trend = ""
            opt_rows.append([n, self.desc.get(n, ""), health, "" if worst is None else round(worst, 2),
                             "" if tx is None else round(tx, 2), trend, reason])
        opt_rows.sort(key=lambda r: (HEALTH_ORDER.get(r[2], 9), natural_key(r[0])))
        return flap_rows, down_rows, opt_rows

    def compute_health(self, flap_rows, down_rows, opt_rows):
        if not self.terse and not self.optics:
            return None, ""
        enabled = [n for n, v in self.terse.items() if v["admin"] == "up"]
        score = 100.0
        detail = []
        if enabled:
            score -= 30 * len(down_rows) / len(enabled)
            detail.append(f"{len(down_rows)}/{len(enabled)} enabled ports without link")
        linked = lambda n: self.terse.get(n, {}).get("link") != "down"
        crit = sum(1 for r in opt_rows if r[2] in ("Critical", "No Light") and linked(r[0]))
        warn = sum(1 for r in opt_rows if r[2] == "Warning" and linked(r[0]))
        score -= min(30, crit * 6) + min(15, warn * 2)
        f1h = sum(1 for r in flap_rows if r[3] == "Critical")
        score -= min(15, f1h * 5) + min(10, len(flap_rows) - f1h)
        detail.append(f"{crit} critical / {warn} weak optics on live links")
        detail.append(f"{len(flap_rows)} recent flaps ({f1h} in the last hour)")
        return max(0, int(round(score))), "; ".join(detail)

    def _port_summary(self, name):
        hours = int(self.cfg["flap_window_hours"])
        t = self.terse.get(name, {})
        s = {"description": self.desc.get(name, ""), "admin": t.get("admin"), "link": t.get("link"),
             "warn_default": float(self.cfg["rx_warn_default"]),
             "alarm_default": float(self.cfg["rx_alarm_default"])}
        f = next((x for x in self.flaps if x["interface"] == name), None)
        if f:
            age = f["age"]
            s["flap_age"] = age
            s["flap_text"] = fmt_age(age)
            s["flap_recent"] = age is not None and age <= hours * 3600
            s["last_flapped"] = f["last_flapped"] + ("" if age is None else f" ({fmt_age(age)})")
            if not s["admin"]:
                s["admin"] = "up" if f["admin"].lower().startswith("enabled") else "down"
                s["link"] = f["link"].lower()
        o = self.optics.get(name)
        if o:
            health, worst, reason = evaluate_optics(o, s["warn_default"], s["alarm_default"])
            s.update(health=health, health_reason=reason, rx=worst,
                     tx=min(o["tx"]) if o["tx"] else None, rx_lanes=o["rx"], thr=o["thr"])
        return s

    def _port_info(self, name):
        s = self._port_summary(name)
        if s.get("admin") == "down":
            state = "disabled"
        elif s.get("link") == "down":
            state = "down"
        elif s.get("link") == "up":
            state = "warning" if s.get("health") in ("Warning", "Critical", "No Light") else "up"
        else:
            state = "unknown"
        age = s.get("flap_age")
        dot = "critical" if (age is not None and age < 3600) else ("warning" if s.get("flap_recent") else None)
        tip = [f"<b style='color:{COLORS['interface']}'>{name}</b>"]
        if s.get("description"):
            tip.append(s["description"])
        tip.append(STATE_LABEL[state])
        if s.get("rx") is not None:
            tip.append(f"Rx {s['rx']:.2f} dBm · {s.get('health')}")
        tr = self.trends.get(name)
        if tr and tr[3] >= 2 and abs(tr[2]) >= 0.5:
            tip.append(f"Rx trend {tr[2]:+.1f} dB / {self.cfg['trend_hours']} h")
        if s.get("flap_recent"):
            tip.append(f"Flapped {s.get('flap_text')}")
        return {"state": state, "dot": dot, "tip": "<br>".join(tip)}

    def _all_ports(self):
        names = set(self.terse) | set(self.optics) | {f["interface"] for f in self.flaps}
        return {n for n in names if split_port(n)}

    def _refresh_dashboard(self):
        self.portmap.set_ports({n: self._port_info(n) for n in self._all_ports()})
        self.cli.input.set_interfaces(self.all_interfaces())
        if self.selected_iface and self.detail.isVisible():
            self.detail.show_interface(self.selected_iface, self._port_summary(self.selected_iface), self.device_name)
            self._update_history_view(self.selected_iface)
        flap_rows, down_rows, opt_rows = self._dashboard_rows()
        hours = int(self.cfg["flap_window_hours"])
        self.t_flaps.set_rows(flap_rows, f"No flaps in the last {hours} h")
        self.t_down.set_rows(down_rows)
        self.t_optics.set_rows(opt_rows)

        score, detail = self.compute_health(flap_rows, down_rows, opt_rows)
        self.ring.set_score(score, detail)
        if score != self.score:
            self.score = score
            self.health_changed.emit(score)
            if score is not None and self.host:
                self.inventory.set_health(self.host, score)
        if not self.terse and not self.flaps and not self.optics:
            for k in (self.k_up, self.k_down, self.k_flap, self.k_optics):
                k.set_value("–", "", None)
            self.k_flap.s.setText(f"last {hours} h")
            return
        total = len(self.terse)
        up = sum(1 for v in self.terse.values() if v["link"] == "up")
        self.k_up.set_value(f"{up}/{total}" if total else "–",
                            f"{total - up} not up" if total else "physical ports", "up" if total else None)
        self.k_down.set_value(len(down_rows), "enabled ports without link", "down" if down_rows else "up")
        crit_flaps = sum(1 for r in flap_rows if r[3] == "Critical")
        self.k_flap.set_value(len(flap_rows), f"last {hours} h · {crit_flaps} in last hour",
                              "down" if crit_flaps else ("warning" if flap_rows else "up"))
        crit = sum(1 for r in opt_rows if r[2] in ("Critical", "No Light"))
        warn = sum(1 for r in opt_rows if r[2] == "Warning")
        ok = sum(1 for r in opt_rows if r[2] == "OK")
        if opt_rows:
            self.k_optics.set_value(f"{ok}/{ok + crit + warn}", f"{crit} critical · {warn} warning",
                                    "down" if crit else ("warning" if warn else "up"))
        else:
            self.k_optics.set_value("–", "no optic readings", None)

    def refresh_theme(self):
        self._refresh_dashboard()
        self.ring.update()
        self.portmap.update()

    # ============================================================== Interface 360
    def open_interface(self, name):
        self.selected_iface = name
        self.portmap.set_selected(name)
        self.detail.show_interface(name, self._port_summary(name), self.device_name)
        self._update_history_view(name)
        if not self.detail.isVisible():
            self.detail.show()
            total = sum(self.split.sizes())
            self.split.setSizes([max(500, total - 390), 390])
        self._fetch_interface(name)

    def _update_history_view(self, name):
        try:
            series = self.history.series(self.device_name, name, 72)
        except Exception:
            series = []
        s = self._port_summary(name)
        thr = s.get("thr", {})
        self.detail.set_history(name, series, thr.get("rx_low_warn", s["warn_default"]),
                                thr.get("rx_low_alarm", s["alarm_default"]), self.trends.get(name),
                                int(self.cfg["trend_hours"]))

    def _fetch_interface(self, name):
        s = self.session
        if not s.is_ready:
            return
        s.enqueue(f'show interfaces {name} extensive | match "Physical interface|Description|Speed|MTU|rate|'
                  f'errors|Errors|transitions|Last flapped" | no-more', background=True, tag="detail",
                  callback=lambda j, n=name: self.detail.set_extensive(n, parse_extensive(j.output)))
        s.enqueue(f"show lldp neighbors interface {name} | no-more", background=True, tag="detail",
                  callback=lambda j, n=name: self.detail.set_lldp(n, parse_lldp(j.output, n)))
        s.enqueue(f"show log messages | match {name} | last 15 | no-more", background=True, tag="detail",
                  callback=lambda j, n=name: self.detail.set_logs(n, j.output))

    def close_interface(self):
        self.detail.hide()
        self.selected_iface = None
        self.portmap.set_selected(None)

    def _refresh_interface(self, name):
        self.detail.show_interface(name, self._port_summary(name), self.device_name)
        self._update_history_view(name)
        self._fetch_interface(name)

    # ============================================================== snapshots
    def snapshot_ports(self):
        ports = {}
        for n in self._all_ports():
            s = self._port_summary(n)
            ports[n] = {"admin": s.get("admin"), "link": s.get("link"), "rx": s.get("rx"), "tx": s.get("tx"),
                        "health": s.get("health"), "description": s.get("description", ""),
                        "last_flapped": next((f["last_flapped"] for f in self.flaps if f["interface"] == n), None)}
        return ports

    def open_snapshots(self):
        if not self.device_name:
            QMessageBox.information(self, "Snapshots", "Connect to a switch first.")
            return
        SnapshotsDialog(self.history, self.device_name, self.take_snapshot, self.compare_with_now,
                        self.compare_snapshots, self).exec()

    def take_snapshot(self, label, done=None):
        def save():
            self.history.save_snapshot(self.device_name, label, self.snapshot_ports())
            self.status.emit(f"Snapshot '{label}' saved ({len(self._all_ports())} ports)")
            if done:
                done()
        self.status.emit("Refreshing before taking the snapshot…")
        self.refresh_then(save)

    def compare_with_now(self, snap_id):
        snap = self.history.load_snapshot(snap_id)
        if not snap:
            return

        def show():
            rows = diff_snapshots(snap["ports"], self.snapshot_ports())
            SnapshotDiffDialog(rows, f"{snap['label']} ({datetime.fromtimestamp(snap['ts']):%Y-%m-%d %H:%M})",
                               f"Now ({datetime.now():%H:%M})", self._export_diff, self).show()
        self.status.emit("Refreshing to compare with the snapshot…")
        self.refresh_then(show)

    def compare_snapshots(self, a_id, b_id):
        a, b = self.history.load_snapshot(a_id), self.history.load_snapshot(b_id)
        if a and b:
            if a["ts"] > b["ts"]:
                a, b = b, a
            lab = lambda s: f"{s['label']} ({datetime.fromtimestamp(s['ts']):%Y-%m-%d %H:%M})"
            SnapshotDiffDialog(diff_snapshots(a["ports"], b["ports"]), lab(a), lab(b), self._export_diff, self).show()

    def _export_diff(self, rows, before, after):
        path = self._ask_save_path("Export comparison", f"Changes_{self._stamp()}.xlsx", "Excel workbook (*.xlsx)")
        if not path:
            return
        meta = self._meta()
        meta.update({"Before": before, "After": after})
        try:
            exporters.save_tables_xlsx({"Changes": (["Interface", "Change", "Before", "After"],
                                                    [list(r[:4]) for r in rows])}, path, meta=meta)
            self.status.emit(f"Saved {path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Junos Assurance", f"Could not save:\n{e}")

    # ============================================================== saving
    def _ask_save_path(self, title, default_name, filt):
        start = os.path.join(self.cfg["last_save_dir"] or os.path.expanduser("~"), default_name)
        path, _ = QFileDialog.getSaveFileName(self, title, start, filt)
        if path:
            ext = re.search(r"\*(\.\w+)", filt)
            if ext and not path.lower().endswith(ext.group(1)):
                path += ext.group(1)
            self.cfg["last_save_dir"] = os.path.dirname(path)
            self.cfg.save()
        return path

    def _meta(self):
        return {"Device": self.device_name, "User": self.user, "Jump host": self.jump}

    def _stamp(self):
        host = re.sub(r"[^\w.-]", "_", self.device_name or "junos")
        return f"{host}_{datetime.now():%Y%m%d_%H%M%S}"

    def save_cli(self, fmt):
        text = self.cli.text()
        if not text.strip():
            QMessageBox.information(self, "Junos Assurance", "The CLI is empty – nothing to save.")
            return
        if fmt == "docx":
            path = self._ask_save_path("Save CLI as Word", f"CLI_{self._stamp()}.docx", "Word document (*.docx)")
        else:
            path = self._ask_save_path("Save CLI as Excel", f"CLI_{self._stamp()}.xlsx", "Excel workbook (*.xlsx)")
        if not path:
            return
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            if fmt == "docx":
                exporters.save_text_docx(text, path, meta=self._meta())
            else:
                exporters.save_text_xlsx(text, path, meta=self._meta())
            self.status.emit(f"Saved {path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Junos Assurance", f"Could not save:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()

    def save_auto_output(self):
        if not self.last_auto or self.last_auto[2] is None:
            QMessageBox.information(self, "Junos Assurance", "Run an automation command first – its output will be saved.")
            return
        name, command, out = self.last_auto
        safe = re.sub(r"[^\w-]+", "_", name).strip("_")
        path = self._ask_save_path("Save command output to Excel", f"{safe}_{self._stamp()}.xlsx",
                                   "Excel workbook (*.xlsx)")
        if not path:
            return
        try:
            exporters.save_output_xlsx(command, out, path, meta=self._meta())
            self.status.emit(f"Saved {path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Junos Assurance", f"Could not save:\n{e}")

    def export_dashboard(self):
        flap_rows, down_rows, opt_rows = self._dashboard_rows()
        if not (flap_rows or down_rows or opt_rows or self.terse):
            QMessageBox.information(self, "Junos Assurance", "No dashboard data yet – connect and refresh first.")
            return
        path = self._ask_save_path("Export dashboard", f"Health_{self._stamp()}.xlsx", "Excel workbook (*.xlsx)")
        if not path:
            return
        plain = lambda rows: [[v[0] if isinstance(v, tuple) else v for v in r] for r in rows]
        all_ports = [[n, self.desc.get(n, ""), v["admin"].capitalize(), v["link"].capitalize()]
                     for n, v in sorted(self.terse.items(), key=lambda kv: natural_key(kv[0]))]
        meta = self._meta()
        meta["Health score"] = f"{self.score} ({health_word(self.score)})" if self.score is not None else "–"
        tables = {
            "Flap List": (["Interface", "Description", "Link", "Severity", "Last Flapped", "Age", "Seen"], flap_rows),
            "Admin Up - Link Down": (["Interface", "Description", "Admin", "Link"], down_rows),
            "Port Health (Optics)": (["Interface", "Description", "Health", "Rx dBm", "Tx dBm", "Rx trend", "Detail"],
                                     plain(opt_rows)),
            "All Ports": (["Interface", "Description", "Admin", "Link"], all_ports),
        }
        try:
            exporters.save_tables_xlsx(tables, path, meta=meta)
            self.status.emit(f"Saved {path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Junos Assurance", f"Could not save:\n{e}")
