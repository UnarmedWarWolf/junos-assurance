"""Main window – DNA-Center-style layout.

 ┌ Header: brand · breadcrumb ················ connection pill · user · ⚙ ┐
 │ Sidebar            │ KPI tiles (Ports up · Admin up/Link down · Flaps · Optics)
 │  Connection        │ Flap list │ Admin up / Link down │ Port health (optics)
 │  Automation cmds   │───────────────────────────────────────────────────────
 │  Monitoring        │ CLI (always visible)          │ Automation output
 └────────────────────┴───────────────────────────────────────────────────────┘
"""
import os
import re
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QByteArray
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter, QToolButton, QVBoxLayout, QWidget, QApplication)

from . import exporters
from .commands import CATALOG, categories, render
from .config import APP_NAME
from .parsers import (HEALTH_ORDER, evaluate_optics, fmt_age, parse_descriptions, parse_extensive,
                      parse_flaps, parse_lldp, parse_optics, parse_terse, split_port)
from .portmap import STATE_LABEL, InterfacePanel, PortMapWidget, legend_widget
from .ssh_session import CONNECTING, DISCONNECTED, HOPPING, READY, JunosSession
from .theme import COLORS
from .widgets import (Card, CliConsole, DashletTable, KpiTile, OutputView, ParamDialog, SettingsDialog,
                      VipDialog, field_label)


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


class MainWindow(QMainWindow):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.session = JunosSession(self)
        self.terse, self.desc, self.flaps, self.optics = {}, {}, [], {}
        self.prev_flap = {}
        self.session_flaps = {}
        self.last_auto = None          # (name, command, output)
        self.last_refresh = None
        self.selected_iface = None

        self.setWindowTitle(APP_NAME)
        self.resize(1600, 980)
        self._build_ui()
        self._wire()
        self._load_saved()

        self.mon_timer = QTimer(self)
        self.mon_timer.timeout.connect(self.run_monitor_cycle)
        self.tick = QTimer(self)
        self.tick.timeout.connect(self._update_refresh_label)
        self.tick.start(1000)

    # =============================================================== UI build
    def _build_ui(self):
        page = QWidget()
        page.setObjectName("Page")
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(8)
        side = self._build_sidebar()
        split.addWidget(side)
        split.addWidget(self._build_content())
        self.detail = InterfacePanel()
        self.detail.hide()
        split.addWidget(self.detail)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([310, 1290, 0])
        self.main_split = split
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 12, 12, 12)
        wl.addWidget(split)
        root.addWidget(wrap, 1)
        self.setCentralWidget(page)

        self.busy_label = QLabel("")
        self.statusBar().addPermanentWidget(self.busy_label)
        self.statusBar().showMessage("Ready. Enter your jump host, P-Number and switch hostname, then Connect.")

    def _build_header(self):
        h = QFrame()
        h.setObjectName("Header")
        h.setFixedHeight(56)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(18, 0, 18, 0)
        mark = QLabel("⬢")
        mark.setObjectName("BrandMark")
        brand = QLabel(APP_NAME)
        brand.setObjectName("Brand")
        crumb = QLabel("   |   Assurance  ›  Device 360")
        crumb.setObjectName("Crumb")
        lay.addWidget(mark)
        lay.addWidget(brand)
        lay.addWidget(crumb)
        lay.addStretch(1)
        self.pill = QLabel()
        lay.addWidget(self.pill)
        self.user_label = QLabel()
        self.user_label.setObjectName("Muted")
        lay.addSpacing(14)
        lay.addWidget(self.user_label)
        gear = QToolButton()
        gear.setObjectName("Icon")
        gear.setText("⚙")
        gear.setToolTip("Settings")
        gear.clicked.connect(lambda: self.open_settings())
        lay.addSpacing(6)
        lay.addWidget(gear)
        self._set_pill("Disconnected", COLORS["muted"])
        return h

    def _set_pill(self, text, color):
        self.pill.setText(f"<span style='color:{color}; font-size:16px;'>●</span> "
                          f"<span style='color:{COLORS['text']}; font-weight:600;'>{text}</span>")

    def _build_sidebar(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(270)
        scroll.setMaximumWidth(420)
        inner = QWidget()
        inner.setObjectName("Page")
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 4, 0)
        col.setSpacing(12)

        # ---- Connection
        c = Card("Connection")
        self.bastion = QLineEdit()
        self.bastion.setPlaceholderText("jumphost.example.net[:port]")
        self.username = QLineEdit()
        self.username.setPlaceholderText("P1234567")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Password (VIP token asked on connect)")
        self.remember = QCheckBox("Remember passwords (system keychain)")
        self.dev_creds = QCheckBox("Switch uses a different login")
        self.dev_creds.setToolTip("Tick if the switches use a different domain account than the jump host")
        self.dev_user = QLineEdit()
        self.dev_user.setPlaceholderText("switch username")
        self.dev_pw = QLineEdit()
        self.dev_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.dev_pw.setPlaceholderText("switch password")
        self.dev_box = QWidget()
        dbl = QVBoxLayout(self.dev_box)
        dbl.setContentsMargins(0, 0, 0, 0)
        dbl.setSpacing(6)
        dbl.addWidget(field_label("Switch username"))
        dbl.addWidget(self.dev_user)
        dbl.addWidget(field_label("Switch password"))
        dbl.addWidget(self.dev_pw)
        self.dev_creds.toggled.connect(self.dev_box.setVisible)
        self.hostname = QComboBox()
        self.hostname.setEditable(True)
        self.hostname.lineEdit().setPlaceholderText("switch hostname, e.g. qfx-core-01")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("Primary")
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setObjectName("Danger")
        self.disconnect_btn.setEnabled(False)
        for lab, w in (("Jump host", self.bastion), ("Username (P-Number)", self.username),
                       ("Password", self.password)):
            c.body.addWidget(field_label(lab))
            c.body.addWidget(w)
        c.body.addWidget(self.remember)
        c.body.addWidget(self.dev_creds)
        c.body.addWidget(self.dev_box)
        c.body.addWidget(field_label("Switch hostname"))
        c.body.addWidget(self.hostname)
        row = QHBoxLayout()
        row.addWidget(self.connect_btn, 2)
        row.addWidget(self.disconnect_btn, 1)
        c.body.addLayout(row)
        col.addWidget(c)

        # ---- Automation commands
        a = Card("Automation Commands")
        self.auto_btn = QToolButton()
        self.auto_btn.setObjectName("Dropdown")
        self.auto_btn.setText("Select a command   ")
        self.auto_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.auto_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.auto_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.auto_btn.setMenu(self._build_command_menu())
        a.body.addWidget(self.auto_btn)
        hint = QLabel("Hover a command for its description. Commands that need an interface or "
                      "other value will ask for it.")
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        a.body.addWidget(hint)
        self.save_auto_btn = QPushButton("Save last output to Excel…")
        self.save_auto_btn.clicked.connect(lambda: self.save_auto_output())
        a.body.addWidget(self.save_auto_btn)
        col.addWidget(a)

        # ---- Monitoring
        m = Card("Background Monitoring")
        self.refresh_label = QLabel("Not running")
        self.refresh_label.setObjectName("Muted")
        self.refresh_label.setWordWrap(True)
        m.body.addWidget(self.refresh_label)
        self.pause_mon = QCheckBox("Pause background checks")
        m.body.addWidget(self.pause_mon)
        r2 = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh now")
        self.refresh_btn.clicked.connect(lambda: self.run_monitor_cycle())
        self.export_btn = QPushButton("Export…")
        self.export_btn.setToolTip("Export the dashboard tables to Excel")
        self.export_btn.clicked.connect(lambda: self.export_dashboard())
        r2.addWidget(self.refresh_btn)
        r2.addWidget(self.export_btn)
        m.body.addLayout(r2)
        col.addWidget(m)
        col.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    def _build_command_menu(self):
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        for cat in categories():
            sub = menu.addMenu(cat)
            sub.setToolTipsVisible(True)
            for cmd in [c for c in CATALOG if c.category == cat]:
                label = cmd.name + ("  …" if cmd.params else "")
                act = sub.addAction(label)
                act.setToolTip(f"<b>{cmd.name}</b><br>{cmd.description}"
                               f"<br><br><span style='font-family:monospace;color:{COLORS['muted']}'>"
                               f"{cmd.template.replace('<', '&lt;').replace('[[', '[').replace(']]', ']')}</span>")
                act.setStatusTip(cmd.description)
                act.triggered.connect(lambda _=False, c=cmd: self.run_automation(c))
        menu.addSeparator()
        save = menu.addAction("💾  Save last command output to Excel…")
        save.setToolTip("Save the output of the last automation command to an .xlsx file")
        save.triggered.connect(lambda _=False: self.save_auto_output())
        return menu

    def _build_content(self):
        w = QWidget()
        w.setObjectName("Page")
        col = QVBoxLayout(w)
        col.setContentsMargins(4, 0, 0, 0)
        col.setSpacing(12)

        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        self.k_up = KpiTile("Ports Up", "physical ports")
        self.k_down = KpiTile("Admin Up · Link Down", "enabled ports without link")
        self.k_flap = KpiTile("Recent Flaps", "")
        self.k_optics = KpiTile("Optics Health", "")
        for k in (self.k_up, self.k_down, self.k_flap, self.k_optics):
            kpis.addWidget(k, 1)
        col.addLayout(kpis)

        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.setHandleWidth(10)
        top = QSplitter(Qt.Orientation.Horizontal)
        top.setHandleWidth(10)
        self.t_flaps = DashletTable("Flap List", ["Interface", "Description", "Link", "Severity",
                                                  "Last Flapped", "Age", "Seen"],
                                    "No recent flaps")
        self.t_down = DashletTable("Admin Up · Link Down", ["Interface", "Description", "Admin", "Link"],
                                   "All enabled ports have link")
        self.t_optics = DashletTable("Port Health (Optics)", ["Interface", "Description", "Health",
                                                              "Rx dBm", "Tx dBm", "Detail"],
                                     "No optic readings yet")
        for t in (self.t_flaps, self.t_down, self.t_optics):
            t.row_activated.connect(self._drill_interface)
            top.addWidget(t)
        top.setSizes([430, 380, 480])

        bottom = QSplitter(Qt.Orientation.Horizontal)
        bottom.setHandleWidth(10)
        self.cli = CliConsole()
        self.auto_card = Card("Automation Output")
        self.auto_cmd_label = QLabel("Choose a command from Automation Commands")
        self.auto_cmd_label.setObjectName("Muted")
        self.auto_cmd_label.setWordWrap(True)
        self.auto_view = OutputView()
        self.auto_view.setStyleSheet(f"border:1px solid {COLORS['border']}; border-radius:4px;")
        b_again = QPushButton("Run again")
        b_again.clicked.connect(lambda: self._rerun_auto())
        b_save = QPushButton("Save to Excel…")
        b_save.clicked.connect(lambda: self.save_auto_output())
        self.auto_card.add_title_widget(b_again)
        self.auto_card.add_title_widget(b_save)
        self.auto_card.body.addWidget(self.auto_cmd_label)
        self.auto_card.body.addWidget(self.auto_view, 1)
        self.auto_card.outer.setContentsMargins(10, 10, 10, 10)
        bottom.addWidget(self.cli)
        bottom.addWidget(self.auto_card)
        bottom.setSizes([820, 470])

        pm = Card("Port Map")
        pm.add_title_widget(legend_widget())
        self.portmap = PortMapWidget()
        self.portmap.port_clicked.connect(self.open_interface)
        pm_scroll = QScrollArea()
        pm_scroll.setWidgetResizable(True)
        pm_scroll.setFrameShape(QFrame.Shape.NoFrame)
        pm_scroll.setWidget(self.portmap)
        pm_scroll.setStyleSheet("QScrollArea{background:#FFFFFF;} QScrollArea > QWidget > QWidget{background:#FFFFFF;}")
        hint = QLabel("Click a port for Interface 360")
        hint.setObjectName("Muted")
        pm.body.addWidget(pm_scroll, 1)
        pm.body.addWidget(hint)
        pm.outer.setContentsMargins(14, 10, 14, 8)

        vsplit.addWidget(pm)
        vsplit.addWidget(top)
        vsplit.addWidget(bottom)
        vsplit.setSizes([170, 280, 420])
        col.addWidget(vsplit, 1)
        return w

    # =============================================================== wiring
    def _wire(self):
        s = self.session
        s.console.connect(self.cli.append)
        s.state_changed.connect(self._on_state)
        s.status.connect(lambda m: self.statusBar().showMessage(m, 8000))
        s.error.connect(lambda m: QMessageBox.warning(self, APP_NAME, m))
        s.device_ready.connect(self._on_device_ready)
        s.prompt_changed.connect(self.cli.set_prompt)
        s.secret_requested.connect(self._on_secret_requested)
        s.busy_changed.connect(lambda b: self.busy_label.setText(
            f"<span style='color:{COLORS['accent']}'>● running…</span>" if b else ""))
        self.connect_btn.clicked.connect(lambda: self.do_connect())
        self.disconnect_btn.clicked.connect(lambda: self.session.close_session())
        self.cli.command_entered.connect(self._on_cli_line)
        self.cli.ctrl_c.connect(lambda: self.session.interrupt())
        self.cli.save_requested.connect(self.save_cli)
        self.username.editingFinished.connect(self._username_changed)
        self.hostname.lineEdit().returnPressed.connect(self.do_connect)
        self.pause_mon.toggled.connect(self._pause_toggled)
        self.detail.close_requested.connect(self.close_interface)
        self.detail.refresh_requested.connect(self._refresh_interface)
        self.detail.run_command.connect(self._on_cli_line)

    def _load_saved(self):
        c = self.cfg
        self.bastion.setText(c["bastion"])
        self.username.setText(c["username"])
        self.remember.setChecked(bool(c["remember_password"]))
        self.password.setText(self.cfg.get_password(c["username"]))
        self.dev_creds.setChecked(bool(c["use_device_creds"]))
        self.dev_box.setVisible(bool(c["use_device_creds"]))
        self.dev_user.setText(c["device_username"])
        self.dev_pw.setText(self.cfg.get_device_password(c["device_username"]))
        self.hostname.addItems(c["recent_hosts"])
        self.hostname.setCurrentText("")
        self.user_label.setText(c["username"])
        geo = c["window_geometry"]
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except Exception:
                pass

    def _username_changed(self):
        u = self.username.text().strip().upper()
        self.username.setText(u)
        if u and not self.password.text():
            self.password.setText(self.cfg.get_password(u))

    # =============================================================== connect
    def do_connect(self):
        if self.session.state in (CONNECTING, HOPPING, READY):
            return
        bastion = self.bastion.text().strip()
        user = self.username.text().strip().upper()
        pw = self.password.text()
        host = self.hostname.currentText().strip()
        use_dev = self.dev_creds.isChecked()
        dev_user = self.dev_user.text().strip() if use_dev else ""
        dev_pw = self.dev_pw.text() if use_dev else ""
        if use_dev and not (dev_user and dev_pw):
            QMessageBox.information(self, APP_NAME, "Enter the switch username and password, "
                                                    "or untick 'Switch uses a different login'.")
            return
        missing = [n for n, v in (("Jump host", bastion), ("Username (P-Number)", user),
                                  ("Switch hostname", host)) if not v]
        if missing:
            QMessageBox.information(self, APP_NAME, "Please enter: " + ", ".join(missing))
            return
        dlg = VipDialog(self, need_password=not pw, password=pw)
        if not dlg.exec():
            return
        if dlg.password() is not None:
            pw = dlg.password()
            self.password.setText(pw)
        token = dlg.value()

        c = self.cfg
        c["bastion"], c["username"] = bastion, user
        c["remember_password"] = self.remember.isChecked()
        c.set_password(user, pw, persist=self.remember.isChecked())
        c["use_device_creds"] = use_dev
        if use_dev:
            c["device_username"] = dev_user
            c.set_device_password(dev_user, dev_pw, persist=self.remember.isChecked())
        c.add_recent_host(host)
        c.save()
        self.hostname.blockSignals(True)
        self.hostname.clear()
        self.hostname.addItems(c["recent_hosts"])
        self.hostname.setCurrentText(host)
        self.hostname.blockSignals(False)
        self.user_label.setText(user)

        self._reset_dashboard()
        self._dash_host = None
        self.cli.append(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S}  Connecting to {host} via jump host "
                        f"{bastion} as {user} =====\n")
        self.session.connect_to(bastion, user, pw, token, host, mode=c["connection_mode"],
                                device_username=dev_user, device_password=dev_pw,
                                device_domain=c["device_domain"], hop_template=c["hop_template"],
                                login_template=c["bastion_login_template"], switch_auth=c["switch_auth"],
                                command_timeout=c["command_timeout"])

    def _on_secret_requested(self, msg):
        dlg = VipDialog(self, message=msg + " Enter a new VIP code to send your switch password + code, "
                                            "or leave it blank to send just the password.",
                        allow_empty=True)
        if dlg.exec():
            self.session.send_token(dlg.value())
        else:
            self.session.cancel_token()

    def _on_state(self, st):
        busy = st in (CONNECTING, HOPPING, READY)
        self.connect_btn.setEnabled(not busy)
        self.disconnect_btn.setEnabled(busy)
        for w in (self.bastion, self.username, self.password, self.hostname, self.dev_creds,
                  self.dev_user, self.dev_pw):
            w.setEnabled(not busy)
        if st == DISCONNECTED:
            self._set_pill("Disconnected", COLORS["muted"])
            self.mon_timer.stop()
            self.refresh_label.setText("Not running")
        elif st == CONNECTING:
            self._set_pill("Connecting to jump host…", COLORS["warning"])
        elif st == HOPPING:
            self._set_pill("Jump host connected · reaching switch…", COLORS["warning"])
            self.mon_timer.stop()
        elif st == READY:
            self._set_pill(f"Connected · {self.session.device_host}", COLORS["up"])

    def _on_device_ready(self, host):
        if host != getattr(self, "_dash_host", None):
            self._reset_dashboard()
            self._dash_host = host
        self.setWindowTitle(f"{APP_NAME} — {host}")
        QTimer.singleShot(500, self.run_monitor_cycle)
        self._restart_timer()

    def _restart_timer(self):
        self.mon_timer.stop()
        if self.cfg["monitor_enabled"] and not self.pause_mon.isChecked() and self.session.is_ready:
            self.mon_timer.start(int(self.cfg["poll_interval"]) * 1000)

    def _pause_toggled(self, paused):
        self._restart_timer()
        self._update_refresh_label()

    def open_settings(self):
        if SettingsDialog(self.cfg, self).exec():
            self._restart_timer()
            self._refresh_dashboard()

    # =============================================================== CLI
    def _on_cli_line(self, line):
        if self.session.state == DISCONNECTED:
            self.cli.append("\n% Not connected. Enter your details and press Connect.\n")
            return
        self.session.send_user_line(line)

    def _drill_interface(self, iface):
        self.open_interface(iface)

    # =============================================================== Interface 360
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
        if s.get("flap_recent"):
            tip.append(f"Flapped {s.get('flap_text')}")
        return {"state": state, "dot": dot, "tip": "<br>".join(tip)}

    def _all_ports(self):
        names = set(self.terse) | set(self.optics) | {f["interface"] for f in self.flaps}
        return {n for n in names if split_port(n)}

    def open_interface(self, name):
        self.selected_iface = name
        self.portmap.set_selected(name)
        self.detail.show_interface(name, self._port_summary(name), self.session.device_host)
        if not self.detail.isVisible():
            self.detail.show()
            sizes = self.main_split.sizes()
            self.main_split.setSizes([sizes[0], max(600, sizes[1] - 390), 390])
        self._fetch_interface(name)

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
        self.detail.show_interface(name, self._port_summary(name), self.session.device_host)
        self._fetch_interface(name)

    # =============================================================== automation
    def all_interfaces(self):
        names = set(self.terse) | set(self.optics) | {f["interface"] for f in self.flaps} | set(self.desc)
        return sorted(names, key=natural_key)

    def run_automation(self, cmd):
        if not self.session.is_ready:
            QMessageBox.information(self, APP_NAME, "Connect to a switch first.")
            return
        values = {}
        if cmd.params:
            dlg = ParamDialog(cmd, self.all_interfaces(), self)
            if not dlg.exec():
                return
            values = dlg.values()
        try:
            command = render(cmd, values)
        except ValueError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        self._run_auto_command(cmd.name, command)

    def _run_auto_command(self, name, command):
        self.auto_card.title_label.setText(f"Automation Output — {name}")
        self.auto_cmd_label.setText(f"› {command}")
        self.auto_view.setPlainText(f"Running on {self.session.device_host}…")
        self.last_auto = (name, command, None)
        self.session.enqueue(command, callback=lambda job, n=name: self._auto_done(n, job), tag="auto")

    def _auto_done(self, name, job):
        out = job.output + ("\n\n% Command timed out – output may be incomplete." if job.timed_out else "")
        self.auto_view.setPlainText(out)
        self.last_auto = (name, job.command, out)
        self.statusBar().showMessage(f"'{name}' finished – {len(out.splitlines())} lines", 6000)

    def _rerun_auto(self):
        if self.last_auto and self.session.is_ready:
            self._run_auto_command(self.last_auto[0], self.last_auto[1])

    # =============================================================== monitoring
    def run_monitor_cycle(self):
        s = self.session
        if not s.is_ready or "mon" in s.pending_tags():
            return
        mc = self.cfg["monitor_commands"]
        s.enqueue(mc["terse"], background=True, tag="mon", callback=self._got_terse)
        s.enqueue(mc["descriptions"], background=True, tag="mon", callback=self._got_desc)
        s.enqueue(mc["flaps"], background=True, tag="mon", callback=self._got_flaps)
        s.enqueue(mc["optics"], background=True, tag="mon", callback=self._got_optics)
        self.refresh_label.setText("Refreshing health data…")

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
                self.statusBar().showMessage(f"⚠ {name} flapped ({lf})", 15000)
            self.prev_flap[name] = lf
        self.flaps = rows
        self._refresh_dashboard()

    def _got_optics(self, job):
        self.optics = parse_optics(job.output)
        self.last_refresh = time.time()
        self._refresh_dashboard()
        self._update_refresh_label()

    def _update_refresh_label(self):
        if not self.session.is_ready:
            return
        if "mon" in self.session.pending_tags():
            self.refresh_label.setText("Refreshing health data…")
            return
        parts = []
        if self.last_refresh:
            parts.append(f"Last refresh {datetime.fromtimestamp(self.last_refresh):%H:%M:%S}")
        if self.pause_mon.isChecked() or not self.cfg["monitor_enabled"]:
            parts.append("background checks paused")
        elif self.mon_timer.isActive():
            parts.append(f"next in {max(0, self.mon_timer.remainingTime() // 1000)} s")
        self.refresh_label.setText(" · ".join(parts) or "Waiting…")

    def _reset_dashboard(self):
        if hasattr(self, "detail"):
            self.close_interface()
        self.terse, self.desc, self.flaps, self.optics = {}, {}, [], {}
        self.prev_flap, self.session_flaps = {}, {}
        self.last_refresh = None
        self._refresh_dashboard()

    def _dashboard_rows(self):
        window = int(self.cfg["flap_window_hours"]) * 3600
        # Flaps
        flap_rows = []
        link_of = {n: v["link"] for n, v in self.terse.items()}
        for f in self.flaps:
            age, seen = f["age"], self.session_flaps.get(f["interface"], 0)
            if (age is None or age > window) and not seen:
                continue
            sev = "Critical" if (age is not None and age < 3600) else "Warning"
            flap_rows.append([f["interface"], self.desc.get(f["interface"], ""),
                              f["link"].capitalize() or link_of.get(f["interface"], ""), sev,
                              f["last_flapped"], fmt_age(age), seen or ""])
        flap_rows.sort(key=lambda r: (next((f["age"] for f in self.flaps if f["interface"] == r[0]), 0) or 0))
        # Admin up / link down
        down_rows = [[n, self.desc.get(n, ""), "Up", "Down"]
                     for n, v in self.terse.items() if v["admin"] == "up" and v["link"] == "down"]
        down_rows.sort(key=lambda r: natural_key(r[0]))
        # Optics
        opt_rows = []
        for n, entry in self.optics.items():
            health, worst, reason = evaluate_optics(entry, float(self.cfg["rx_warn_default"]),
                                                    float(self.cfg["rx_alarm_default"]))
            tx = min(entry["tx"]) if entry["tx"] else None
            opt_rows.append([n, self.desc.get(n, ""), health,
                             "" if worst is None else round(worst, 2),
                             "" if tx is None else round(tx, 2), reason])
        opt_rows.sort(key=lambda r: (HEALTH_ORDER.get(r[2], 9), natural_key(r[0])))
        return flap_rows, down_rows, opt_rows

    def _refresh_dashboard(self):
        self.portmap.set_ports({n: self._port_info(n) for n in self._all_ports()})
        if getattr(self, "selected_iface", None) and self.detail.isVisible():
            self.detail.show_interface(self.selected_iface, self._port_summary(self.selected_iface),
                                       self.session.device_host)
        flap_rows, down_rows, opt_rows = self._dashboard_rows()
        hours = int(self.cfg["flap_window_hours"])
        self.t_flaps.set_rows(flap_rows, f"No flaps in the last {hours} h")
        self.t_down.set_rows(down_rows)
        self.t_optics.set_rows(opt_rows)

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

    # =============================================================== saving
    def _ask_save_path(self, title, default_name, filt):
        start = os.path.join(self.cfg["last_save_dir"] or os.path.expanduser("~"), default_name)
        path, _ = QFileDialog.getSaveFileName(self, title, start, filt)
        if path:
            self.cfg["last_save_dir"] = os.path.dirname(path)
            self.cfg.save()
        return path

    def _meta(self):
        return {"Device": self.session.device_host or self.hostname.currentText(),
                "User": self.username.text(), "Jump host": self.bastion.text()}

    def _stamp(self):
        host = re.sub(r"[^\w.-]", "_", self.session.device_host or self.hostname.currentText() or "junos")
        return f"{host}_{datetime.now():%Y%m%d_%H%M%S}"

    def save_cli(self, fmt):
        text = self.cli.text()
        if not text.strip():
            QMessageBox.information(self, APP_NAME, "The CLI is empty – nothing to save.")
            return
        if fmt == "docx":
            path = self._ask_save_path("Save CLI as Word", f"CLI_{self._stamp()}.docx", "Word document (*.docx)")
        else:
            path = self._ask_save_path("Save CLI as Excel", f"CLI_{self._stamp()}.xlsx", "Excel workbook (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith("." + fmt):
            path += "." + fmt
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            if fmt == "docx":
                exporters.save_text_docx(text, path, meta=self._meta())
            else:
                exporters.save_text_xlsx(text, path, meta=self._meta())
            self.statusBar().showMessage(f"Saved {path}", 8000)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Could not save:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()

    def save_auto_output(self):
        if not self.last_auto or self.last_auto[2] is None:
            QMessageBox.information(self, APP_NAME, "Run an automation command first – its output will be saved.")
            return
        name, command, out = self.last_auto
        safe = re.sub(r"[^\w-]+", "_", name).strip("_")
        path = self._ask_save_path("Save command output to Excel", f"{safe}_{self._stamp()}.xlsx",
                                   "Excel workbook (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            exporters.save_output_xlsx(command, out, path, meta=self._meta())
            self.statusBar().showMessage(f"Saved {path}", 8000)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Could not save:\n{e}")

    def export_dashboard(self):
        flap_rows, down_rows, opt_rows = self._dashboard_rows()
        if not (flap_rows or down_rows or opt_rows or self.terse):
            QMessageBox.information(self, APP_NAME, "No dashboard data yet – connect and refresh first.")
            return
        path = self._ask_save_path("Export dashboard", f"Health_{self._stamp()}.xlsx", "Excel workbook (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        all_ports = [[n, self.desc.get(n, ""), v["admin"].capitalize(), v["link"].capitalize()]
                     for n, v in sorted(self.terse.items(), key=lambda kv: natural_key(kv[0]))]
        tables = {
            "Flap List": (["Interface", "Description", "Link", "Severity", "Last Flapped", "Age", "Seen"], flap_rows),
            "Admin Up - Link Down": (["Interface", "Description", "Admin", "Link"], down_rows),
            "Port Health (Optics)": (["Interface", "Description", "Health", "Rx dBm", "Tx dBm", "Detail"], opt_rows),
            "All Ports": (["Interface", "Description", "Admin", "Link"], all_ports),
        }
        try:
            exporters.save_tables_xlsx(tables, path, meta=self._meta())
            self.statusBar().showMessage(f"Saved {path}", 8000)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Could not save:\n{e}")

    # =============================================================== close
    def closeEvent(self, e):
        self.cfg["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        self.cfg["bastion"] = self.bastion.text().strip()
        self.cfg["username"] = self.username.text().strip().upper()
        self.cfg["remember_password"] = self.remember.isChecked()
        self.cfg["use_device_creds"] = self.dev_creds.isChecked()
        if self.dev_user.text().strip():
            self.cfg["device_username"] = self.dev_user.text().strip()
            if self.remember.isChecked() and self.dev_pw.text():
                self.cfg.set_device_password(self.cfg["device_username"], self.dev_pw.text(), persist=True)
        if self.remember.isChecked() and self.password.text():
            self.cfg.set_password(self.cfg["username"], self.password.text(), persist=True)
        elif not self.remember.isChecked():
            self.cfg.delete_password(self.cfg["username"])
        self.cfg.save()
        self.session.close_session()
        super().closeEvent(e)
