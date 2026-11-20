"""Main window – DNA-Center-style shell.

 ┌ Header: brand · breadcrumb ········· connection pill · 🔔 alerts · ☾ theme · user · ⚙ ┐
 │ Icon │ Side panel (collapsible)   │ Device tabs  [qfx-01 ●] [edw-02 ●] [+]           │
 │ rail │ Connect / Devices /        │  Health ring · KPI tiles                          │
 │      │ Commands / Monitor         │  Port map / Flap · Down · Optics tables           │
 │      │                            │  CLI │ Automation output        │ Interface 360   │
 └──────┴────────────────────────────┴───────────────────────────────────────────────────┘
"""
import os
from datetime import datetime

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QCompleter, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QSystemTrayIcon, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from .commands import CATALOG, categories
from .config import APP_NAME, HISTORY_DB, INVENTORY_FILE
from .device_tab import DeviceTab
from .dialogs import DeviceEditDialog
from .history import History
from .inventory import Inventory
from .playbooks import PLAYBOOKS
from .session_log import default_log_dir
from .ssh_session import CONNECTING, DISCONNECTED, HOPPING, READY
from .theme import COLORS, STATUS_HEX, apply_theme
from .widgets import (Card, SettingsDialog, VipDialog, field_label, health_key, health_word, refresh_themed_widgets)


def dot_icon(color, size=12):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pm)


def app_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#049FD9"))
    p.setPen(Qt.PenStyle.NoPen)
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    import math
    pts = [QPointF(32 + 28 * math.cos(math.radians(60 * i - 30)), 32 + 28 * math.sin(math.radians(60 * i - 30)))
           for i in range(6)]
    p.drawPolygon(QPolygonF(pts))
    p.setBrush(QColor("#FFFFFF"))
    p.drawEllipse(22, 22, 20, 20)
    p.end()
    return QIcon(pm)


NAV = [("connect", "⇄", "Connect"), ("devices", "▦", "Devices"), ("commands", "❯_", "Commands"),
       ("monitor", "◷", "Monitor")]


class MainWindow(QMainWindow):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.history = History(HISTORY_DB)
        self.inventory = Inventory(INVENTORY_FILE)
        for h in cfg["recent_hosts"]:           # bring older recent-host lists into the inventory
            if not self.inventory.get(h):
                self.inventory.touch(h)
        self.alerts = []                        # (time, title, message, key)
        self.unread = 0

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1680, 1000)
        self._build_ui()
        self._load_saved()

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(app_icon(), self)
            self.tray.setToolTip(APP_NAME)
            self.tray.messageClicked.connect(self._show_from_tray)
            self.tray.show()

        self.tick = QTimer(self)
        self.tick.timeout.connect(self._tick)
        self.tick.start(1000)

    # ================================================================ build
    def _build_ui(self):
        page = QWidget()
        page.setObjectName("Page")
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_rail())
        self.side = QStackedWidget()
        self.side.setObjectName("Stack")
        self.side.setFixedWidth(320)
        self.pages = {}
        for key, builder in (("connect", self._page_connect), ("devices", self._page_devices),
                             ("commands", self._page_commands), ("monitor", self._page_monitor)):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            inner = QWidget()
            inner.setObjectName("Page")
            col = QVBoxLayout(inner)
            col.setContentsMargins(12, 12, 8, 12)
            col.setSpacing(12)
            builder(col)
            col.addStretch(1)
            scroll.setWidget(inner)
            self.side.addWidget(scroll)
            self.pages[key] = scroll
        body.addWidget(self.side)

        self.main_stack = QStackedWidget()
        self.main_stack.setObjectName("Stack")
        self.welcome = self._build_welcome()
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        plus = QToolButton()
        plus.setObjectName("Flat")
        plus.setText("+  New")
        plus.setToolTip("Connect to another switch in a new tab")
        plus.clicked.connect(self._new_connection)
        self.tabs.setCornerWidget(plus, Qt.Corner.TopRightCorner)
        self.main_stack.addWidget(self.welcome)
        self.main_stack.addWidget(self.tabs)
        wrap = QWidget()
        wrap.setObjectName("Page")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 8, 12, 12)
        wl.addWidget(self.main_stack)
        body.addWidget(wrap, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(page)

        self.busy_label = QLabel("")
        self.statusBar().addPermanentWidget(self.busy_label)
        self.statusBar().showMessage("Ready. Enter your jump host, P-Number and a switch, then Connect.")

    def _build_header(self):
        h = QFrame()
        h.setObjectName("Header")
        h.setFixedHeight(56)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(18, 0, 14, 0)
        mark = QLabel("⬢")
        mark.setObjectName("BrandMark")
        brand = QLabel(APP_NAME)
        brand.setObjectName("Brand")
        self.crumb = QLabel()
        self.crumb.setObjectName("Crumb")
        lay.addWidget(mark)
        lay.addWidget(brand)
        lay.addWidget(self.crumb)
        lay.addStretch(1)
        self.pill = QLabel()
        lay.addWidget(self.pill)
        lay.addSpacing(10)
        self.bell = QToolButton()
        self.bell.setObjectName("Icon")
        self.bell.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.bell_menu = QMenu(self.bell)
        self.bell_menu.aboutToShow.connect(self._fill_bell)
        self.bell.setMenu(self.bell_menu)
        self.bell.setToolTip("Alerts")
        lay.addWidget(self.bell)
        self.theme_btn = QToolButton()
        self.theme_btn.setObjectName("Icon")
        self.theme_btn.setToolTip("Toggle dark mode")
        self.theme_btn.clicked.connect(self.toggle_theme)
        lay.addWidget(self.theme_btn)
        self.user_label = QLabel()
        self.user_label.setObjectName("Muted")
        lay.addSpacing(8)
        lay.addWidget(self.user_label)
        gear = QToolButton()
        gear.setObjectName("Icon")
        gear.setText("⚙")
        gear.setToolTip("Settings")
        gear.clicked.connect(self.open_settings)
        lay.addWidget(gear)
        self._update_bell()
        self._set_pill("No device", COLORS["muted"])
        self._update_crumb()
        return h

    def _build_rail(self):
        rail = QFrame()
        rail.setObjectName("NavRail")
        rail.setFixedWidth(78)
        col = QVBoxLayout(rail)
        col.setContentsMargins(7, 10, 7, 10)
        col.setSpacing(4)
        self.nav_buttons = {}
        for key, icon, label in NAV:
            b = QToolButton()
            b.setObjectName("Nav")
            b.setText(f"{icon}\n{label}")
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setMinimumHeight(54)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k, toggle=True))
            col.addWidget(b)
            self.nav_buttons[key] = b
        col.addStretch(1)
        s = QToolButton()
        s.setObjectName("Nav")
        s.setText("⚙\nSettings")
        s.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        s.setMinimumHeight(54)
        s.clicked.connect(self.open_settings)
        col.addWidget(s)
        return rail

    def show_page(self, key, toggle=False):
        if toggle and self.side.isVisible() and self.side.currentWidget() is self.pages.get(key):
            self.side.hide()
            for b in self.nav_buttons.values():
                b.setChecked(False)
            self.cfg["nav_page"] = ""
            return
        self.side.setCurrentWidget(self.pages[key])
        self.side.show()
        for k, b in self.nav_buttons.items():
            b.setChecked(k == key)
        self.cfg["nav_page"] = key
        if key == "devices":
            self._reload_devices()

    def _build_welcome(self):
        w = QWidget()
        w.setObjectName("Page")
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        t = QLabel("⬢")
        t.setStyleSheet(f"font-size:56px; color:{COLORS['accent']};")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h = QLabel("Connect to a switch to get started")
        h.setStyleSheet("font-size:20px; font-weight:600;")
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d = QLabel("Use Connect on the left, or double-click a switch in Devices.\n"
                   "Each switch opens in its own tab, so you can keep several open at once.")
        d.setObjectName("Muted")
        d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for x in (t, h, d):
            lay.addWidget(x)
        lay.addStretch(2)
        return w

    # -------------------------------------------------------------- pages
    def _page_connect(self, col):
        c = Card("Connection")
        self.bastion = QLineEdit()
        self.bastion.setPlaceholderText("jumphost.example.net[:port]")
        self.username = QLineEdit()
        self.username.setPlaceholderText("P1234567")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Password (VIP code asked on connect)")
        self.remember = QCheckBox("Remember passwords (system keychain)")
        self.dev_creds = QCheckBox("Switch uses a different login")
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
        self.hostname.lineEdit().returnPressed.connect(self.do_connect)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("Primary")
        self.connect_btn.clicked.connect(lambda: self.do_connect())
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setObjectName("Danger")
        self.disconnect_btn.clicked.connect(lambda: self.current_tab() and self.current_tab().disconnect_device())
        for lab, w in (("Jump host", self.bastion), ("Username (P-Number)", self.username), ("Password", self.password)):
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
        hint = QLabel("Connect opens a new tab if the current tab is already connected.")
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        c.body.addWidget(hint)
        self.username.editingFinished.connect(self._username_changed)
        col.addWidget(c)

    def _page_devices(self, col):
        c = Card("Devices")
        self.dev_search = QLineEdit()
        self.dev_search.setPlaceholderText("Search name, site, role, tags…")
        self.dev_search.setClearButtonEnabled(True)
        self.dev_search.textChanged.connect(lambda _t: self._reload_devices())
        self.dev_list = QListWidget()
        self.dev_list.setMinimumHeight(360)
        self.dev_list.itemDoubleClicked.connect(lambda it: self._connect_to(it.data(Qt.ItemDataRole.UserRole)))
        c.body.addWidget(self.dev_search)
        c.body.addWidget(self.dev_list, 1)
        r1 = QHBoxLayout()
        b_conn = QPushButton("Connect")
        b_conn.setObjectName("Primary")
        b_conn.clicked.connect(lambda: self._sel_device() and self._connect_to(self._sel_device()))
        b_fav = QPushButton("★")
        b_fav.setToolTip("Favorite / unfavorite")
        b_fav.clicked.connect(self._toggle_fav)
        r1.addWidget(b_conn, 2)
        r1.addWidget(b_fav)
        c.body.addLayout(r1)
        r2 = QHBoxLayout()
        for text, fn in (("Add", self._add_device), ("Edit", self._edit_device), ("Remove", self._remove_device)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            r2.addWidget(b)
        c.body.addLayout(r2)
        r3 = QHBoxLayout()
        bi = QPushButton("Import CSV…")
        bi.setToolTip("Columns: hostname, site, role, tags, notes (header row optional)")
        bi.clicked.connect(self._import_csv)
        be = QPushButton("Export CSV…")
        be.clicked.connect(self._export_csv)
        r3.addWidget(bi)
        r3.addWidget(be)
        c.body.addLayout(r3)
        hint = QLabel("Double-click a switch to connect. Switches you connect to are added automatically. "
                      "The dot shows the last health score.")
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        c.body.addWidget(hint)
        col.addWidget(c)

    def _page_commands(self, col):
        a = Card("Automation Commands")
        self.auto_btn = QToolButton()
        self.auto_btn.setObjectName("Dropdown")
        self.auto_btn.setText("Select a command   ")
        self.auto_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.auto_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.auto_btn.setMenu(self._build_command_menu())
        a.body.addWidget(self.auto_btn)
        hint = QLabel("Hover over a command for its description. Commands that need an interface or other value "
                      "will ask for it. Output appears in the current tab.")
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        a.body.addWidget(hint)
        for text, fn in (("Save last output to Excel…", lambda t: t.save_auto_output()),
                         ("Explain last output", lambda t: t.explain_auto())):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: self._on_tab(f))
            a.body.addWidget(b)
        col.addWidget(a)

        p = Card("Troubleshooting Playbooks")
        d = QLabel("Guided checks that run the right commands in order and explain the most likely cause.")
        d.setWordWrap(True)
        d.setObjectName("Muted")
        p.body.addWidget(d)
        for pb in PLAYBOOKS:
            b = QPushButton(pb.name)
            b.setToolTip(pb.description)
            b.clicked.connect(lambda _=False, k=pb.key: self._on_tab(lambda t: t.run_playbook(k)))
            p.body.addWidget(b)
        col.addWidget(p)

    def _page_monitor(self, col):
        m = Card("Background Monitoring")
        self.refresh_label = QLabel("Not connected")
        self.refresh_label.setObjectName("Muted")
        self.refresh_label.setWordWrap(True)
        m.body.addWidget(self.refresh_label)
        self.pause_mon = QCheckBox("Pause background checks (this tab)")
        self.pause_mon.toggled.connect(self._pause_toggled)
        m.body.addWidget(self.pause_mon)
        r = QHBoxLayout()
        b1 = QPushButton("Refresh now")
        b1.clicked.connect(lambda: self._on_tab(lambda t: t.run_monitor_cycle(force=True)))
        b2 = QPushButton("Export…")
        b2.setToolTip("Export the dashboard tables to Excel")
        b2.clicked.connect(lambda: self._on_tab(lambda t: t.export_dashboard()))
        r.addWidget(b1)
        r.addWidget(b2)
        m.body.addLayout(r)
        col.addWidget(m)

        s = Card("Before / After Snapshots")
        d = QLabel("Snapshot every port before maintenance, then compare afterwards to see what changed.")
        d.setWordWrap(True)
        d.setObjectName("Muted")
        s.body.addWidget(d)
        b_take = QPushButton("Take snapshot now")
        b_take.setObjectName("Primary")
        b_take.clicked.connect(self._quick_snapshot)
        b_list = QPushButton("Snapshots && compare…")
        b_list.clicked.connect(lambda: self._on_tab(lambda t: t.open_snapshots()))
        s.body.addWidget(b_take)
        s.body.addWidget(b_list)
        col.addWidget(s)

        al = Card("Alerts")
        self.alerts_on = QCheckBox("Desktop notifications")
        self.alerts_on.toggled.connect(self._alerts_toggled)
        al.body.addWidget(self.alerts_on)
        self.alert_list = QListWidget()
        self.alert_list.setMinimumHeight(160)
        self.alert_list.setWordWrap(True)
        al.body.addWidget(self.alert_list)
        bc = QPushButton("Clear alerts")
        bc.clicked.connect(self._clear_alerts)
        al.body.addWidget(bc)
        col.addWidget(al)

        lg = Card("Session Logs")
        self.logging_on = QCheckBox("Log every session automatically")
        self.logging_on.toggled.connect(self._logging_toggled)
        lg.body.addWidget(self.logging_on)
        self.log_label = QLabel("")
        self.log_label.setObjectName("Muted")
        self.log_label.setWordWrap(True)
        self.log_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lg.body.addWidget(self.log_label)
        bo = QPushButton("Open logs folder")
        bo.clicked.connect(self._open_logs)
        lg.body.addWidget(bo)
        col.addWidget(lg)

    def _build_command_menu(self):
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        for cat in categories():
            sub = menu.addMenu(cat)
            sub.setToolTipsVisible(True)
            for cmd in [c for c in CATALOG if c.category == cat]:
                act = sub.addAction(cmd.name + ("  …" if cmd.params else ""))
                act.setToolTip(f"<b>{cmd.name}</b><br>{cmd.description}"
                               f"<br><br><span style='font-family:monospace'>"
                               f"{cmd.template.replace('<', '&lt;').replace('[[', '[').replace(']]', ']')}</span>")
                act.setStatusTip(cmd.description)
                act.triggered.connect(lambda _=False, c=cmd: self._on_tab(lambda t: t.run_automation(c)))
        pbm = menu.addMenu("Troubleshooting Playbooks")
        pbm.setToolTipsVisible(True)
        for pb in PLAYBOOKS:
            act = pbm.addAction(pb.name + "  …")
            act.setToolTip(pb.description)
            act.triggered.connect(lambda _=False, k=pb.key: self._on_tab(lambda t: t.run_playbook(k)))
        menu.addSeparator()
        save = menu.addAction("💾  Save last command output to Excel…")
        save.triggered.connect(lambda _=False: self._on_tab(lambda t: t.save_auto_output()))
        return menu

    # ============================================================ saved state
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
        self._reload_hostnames()
        self.user_label.setText(c["username"])
        self.alerts_on.setChecked(bool(c["alerts_enabled"]))
        self.logging_on.setChecked(bool(c["session_logging"]))
        self._update_log_label()
        self.theme_btn.setText("☀" if c["dark_mode"] else "☾")
        geo = c["window_geometry"]
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except Exception:
                pass
        if c["nav_page"] in self.pages:
            self.show_page(c["nav_page"])
        else:
            self.side.hide()

    def _reload_hostnames(self):
        current = self.hostname.currentText()
        names = [d.hostname for d in self.inventory.search()]
        self.hostname.blockSignals(True)
        self.hostname.clear()
        self.hostname.addItems(names)
        self.hostname.setCurrentText(current)
        self.hostname.blockSignals(False)
        comp = QCompleter(names, self.hostname)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        self.hostname.setCompleter(comp)

    def _username_changed(self):
        u = self.username.text().strip().upper()
        self.username.setText(u)
        if u and not self.password.text():
            self.password.setText(self.cfg.get_password(u))

    # ================================================================ tabs
    def current_tab(self):
        tabs = getattr(self, "tabs", None)       # may be called while the window is still being built
        w = tabs.currentWidget() if tabs is not None else None
        return w if isinstance(w, DeviceTab) else None

    def _on_tab(self, fn):
        t = self.current_tab()
        if t is None:
            QMessageBox.information(self, APP_NAME, "Connect to a switch first.")
            self.show_page("connect")
            return
        fn(t)

    def new_tab(self):
        t = DeviceTab(self.cfg, self.history, self.inventory)
        t.alert.connect(lambda title, msg, key, tab=t: self.on_alert(tab, title, msg, key))
        t.health_changed.connect(lambda _s, tab=t: self._update_tab_icon(tab))
        t.state_changed.connect(lambda _s, tab=t: self._tab_state(tab))
        t.status.connect(lambda m: self.statusBar().showMessage(m, 8000))
        t.title_changed.connect(lambda title, tab=t: self._set_tab_title(tab, title))
        t.session.busy_changed.connect(lambda b, tab=t: self._busy(tab, b))
        idx = self.tabs.addTab(t, dot_icon(COLORS["muted"]), "New")
        self.tabs.setCurrentIndex(idx)
        self.main_stack.setCurrentWidget(self.tabs)
        return t

    def _set_tab_title(self, tab, title):
        i = self.tabs.indexOf(tab)
        if i >= 0:
            self.tabs.setTabText(i, title or "New")
            self.tabs.setTabToolTip(i, title)
        if tab is self.current_tab():
            self._update_crumb()

    def _update_tab_icon(self, tab):
        i = self.tabs.indexOf(tab)
        if i < 0:
            return
        st = tab.state
        if st == DISCONNECTED:
            col = COLORS["muted"]
        elif st in (CONNECTING, HOPPING):
            col = COLORS["warning"]
        else:
            col = STATUS_HEX.get(health_key(tab.score), COLORS["up"])
        self.tabs.setTabIcon(i, dot_icon(col))
        if st == READY and tab.score is not None:
            self.tabs.setTabToolTip(i, f"{tab.device_name} – health {tab.score} ({health_word(tab.score)})")
        if tab is self.current_tab():
            self._update_pill()
        if self.side.currentWidget() is self.pages["devices"] and self.side.isVisible():
            self._reload_devices()

    def _tab_state(self, tab):
        self._update_tab_icon(tab)
        if tab is self.current_tab():
            self._update_pill()
            self._update_connect_buttons()

    def _tab_changed(self, _i):
        self._update_pill()
        self._update_crumb()
        self._update_connect_buttons()
        t = self.current_tab()
        self.pause_mon.blockSignals(True)
        self.pause_mon.setChecked(bool(t and getattr(t, "paused", False)))
        self.pause_mon.blockSignals(False)
        if t is None:
            self.main_stack.setCurrentWidget(self.welcome)

    def _busy(self, tab, busy):
        if tab is self.current_tab():
            self.busy_label.setText(f"<span style='color:{COLORS['accent']}'>● running…</span>" if busy else "")

    def close_tab(self, index):
        t = self.tabs.widget(index)
        if not isinstance(t, DeviceTab):
            return
        if t.state != DISCONNECTED and QMessageBox.question(
                self, APP_NAME, f"Disconnect from {t.device_name} and close this tab?") != QMessageBox.StandardButton.Yes:
            return
        t.shutdown()
        self.tabs.removeTab(index)
        t.deleteLater()
        if self.tabs.count() == 0:
            self.main_stack.setCurrentWidget(self.welcome)
        self._tab_changed(self.tabs.currentIndex())

    def _new_connection(self):
        self.show_page("connect")
        self.hostname.setFocus()
        self.hostname.lineEdit().selectAll()

    # ============================================================== header
    def _set_pill(self, text, color):
        self.pill.setText(f"<span style='color:{color}; font-size:16px;'>●</span> "
                          f"<span style='font-weight:600;'>{text}</span>")

    def _update_pill(self):
        t = self.current_tab()
        if t is None:
            self._set_pill("No device", COLORS["muted"])
            return
        st = t.state
        if st == DISCONNECTED:
            self._set_pill(f"{t.device_name or 'Tab'} · Disconnected", COLORS["muted"])
        elif st == CONNECTING:
            self._set_pill("Connecting to jump host…", COLORS["warning"])
        elif st == HOPPING:
            self._set_pill("Jump host connected · reaching switch…", COLORS["warning"])
        else:
            extra = f" · Health {t.score}" if t.score is not None else ""
            self._set_pill(f"Connected · {t.device_name}{extra}", STATUS_HEX.get(health_key(t.score), COLORS["up"]))

    def _update_crumb(self):
        t = self.current_tab()
        name = t.device_name if t else ""
        self.crumb.setText("   |   Assurance  ›  Device 360" + (f"  ›  {name}" if name else ""))

    def _update_connect_buttons(self):
        t = self.current_tab()
        self.disconnect_btn.setEnabled(bool(t and t.state != DISCONNECTED))

    def _update_bell(self):
        self.bell.setText(f"🔔 {self.unread}" if self.unread else "🔔")
        self.bell.setStyleSheet(f"color:{COLORS['down']}; font-weight:700;" if self.unread else "")

    def _fill_bell(self):
        self.bell_menu.clear()
        if not self.alerts:
            a = self.bell_menu.addAction("No alerts")
            a.setEnabled(False)
        for ts, title, msg, key in self.alerts[:15]:
            a = self.bell_menu.addAction(dot_icon(STATUS_HEX.get(key, COLORS["muted"])),
                                         f"{ts:%H:%M}  {title}")
            a.setToolTip(msg)
        self.bell_menu.addSeparator()
        self.bell_menu.addAction("Show all in Monitor", lambda: self.show_page("monitor"))
        self.bell_menu.addAction("Clear alerts", self._clear_alerts)
        self.unread = 0
        self._update_bell()

    # ============================================================== connect
    def do_connect(self, hostname=None):
        host = (hostname or self.hostname.currentText()).strip()
        bastion = self.bastion.text().strip()
        user = self.username.text().strip().upper()
        pw = self.password.text()
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
            self.show_page("connect")
            QMessageBox.information(self, APP_NAME, "Please enter: " + ", ".join(missing))
            return
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            if isinstance(t, DeviceTab) and t.host.lower() == host.lower() and t.state != DISCONNECTED:
                self.tabs.setCurrentIndex(i)
                self.statusBar().showMessage(f"{host} is already open in a tab.", 6000)
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
        self.inventory.touch(host)
        self._reload_hostnames()
        self.hostname.setCurrentText(host)
        self.user_label.setText(user)

        t = self.current_tab()
        if t is None or t.state != DISCONNECTED:
            t = self.new_tab()
        t.connect_device(bastion, user, pw, token, host, dev_user, dev_pw)
        self._tab_changed(self.tabs.currentIndex())

    def _connect_to(self, hostname):
        if hostname:
            self.hostname.setCurrentText(hostname)
            self.do_connect(hostname)

    # ============================================================== devices
    def _reload_devices(self):
        sel = self._sel_device()
        self.dev_list.clear()
        for d in self.inventory.search(self.dev_search.text()):
            open_tab = any(isinstance(self.tabs.widget(i), DeviceTab) and self.tabs.widget(i).host.lower() ==
                           d.hostname.lower() and self.tabs.widget(i).state != DISCONNECTED
                           for i in range(self.tabs.count()))
            title = ("★ " if d.favorite else "") + d.hostname + ("   (open)" if open_tab else "")
            it = QListWidgetItem(title + "\n" + (d.subtitle() or "No site/role yet"))
            it.setData(Qt.ItemDataRole.UserRole, d.hostname)
            it.setIcon(dot_icon(STATUS_HEX.get(health_key(d.health), COLORS["border"])))
            tip = [d.hostname]
            if d.health >= 0:
                tip.append(f"Last health score {d.health} ({health_word(d.health)})")
            if d.last_connected:
                tip.append(f"Last connected {datetime.fromtimestamp(d.last_connected):%Y-%m-%d %H:%M}")
            if d.notes:
                tip.append(d.notes)
            it.setToolTip("\n".join(tip))
            self.dev_list.addItem(it)
            if d.hostname == sel:
                self.dev_list.setCurrentItem(it)

    def _sel_device(self):
        it = self.dev_list.currentItem() if hasattr(self, "dev_list") else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _toggle_fav(self):
        h = self._sel_device()
        if h:
            self.inventory.toggle_favorite(h)
            self._reload_devices()

    def _add_device(self):
        dlg = DeviceEditDialog(None, self)
        if dlg.exec():
            self.inventory.upsert(dlg.result_device())
            self._reload_devices()
            self._reload_hostnames()

    def _edit_device(self):
        h = self._sel_device()
        dev = self.inventory.get(h) if h else None
        if not dev:
            return
        dlg = DeviceEditDialog(dev, self)
        if dlg.exec():
            self.inventory.upsert(dlg.result_device(), old_hostname=dev.hostname)
            self._reload_devices()
            self._reload_hostnames()

    def _remove_device(self):
        h = self._sel_device()
        if h and QMessageBox.question(self, APP_NAME, f"Remove {h} from the device list?") == \
                QMessageBox.StandardButton.Yes:
            self.inventory.remove(h)
            self.cfg["recent_hosts"] = [x for x in self.cfg["recent_hosts"] if x.lower() != h.lower()]
            self.cfg.save()
            self._reload_devices()
            self._reload_hostnames()

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import devices", self.cfg["last_save_dir"], "CSV files (*.csv)")
        if path:
            try:
                n = self.inventory.import_csv(path)
                self.statusBar().showMessage(f"Imported {n} devices", 8000)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, APP_NAME, f"Could not import:\n{e}")
            self._reload_devices()
            self._reload_hostnames()

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export devices",
                                              os.path.join(self.cfg["last_save_dir"], "devices.csv"), "CSV files (*.csv)")
        if path:
            if not path.lower().endswith(".csv"):
                path += ".csv"
            self.inventory.export_csv(path)
            self.statusBar().showMessage(f"Saved {path}", 8000)

    # ============================================================== monitor page
    def _tick(self):
        t = self.current_tab()
        self.refresh_label.setText(t.refresh_text() if t else "Not connected")
        if t and t.logger and t.logger.path.exists():
            self.log_label.setText(f"This tab: {t.logger.path}")

    def _pause_toggled(self, paused):
        t = self.current_tab()
        if t:
            t.restart_timer(paused)

    def _quick_snapshot(self):
        t = self.current_tab()
        if not t:
            return self._on_tab(lambda _t: None)
        label = f"Snapshot {datetime.now():%Y-%m-%d %H:%M}"
        t.take_snapshot(label, lambda: QMessageBox.information(
            self, "Snapshot saved", f"Saved '{label}' for {t.device_name}.\n\nAfter your change, open "
                                    "'Snapshots & compare…' and choose 'Compare with now'."))

    # ================================================================ alerts
    def on_alert(self, tab, title, message, key):
        now = datetime.now()
        self.alerts.insert(0, (now, title, message, key))
        del self.alerts[200:]
        it = QListWidgetItem(dot_icon(STATUS_HEX.get(key, COLORS["muted"])), f"{now:%H:%M:%S}  {title}\n{message}")
        self.alert_list.insertItem(0, it)
        while self.alert_list.count() > 200:
            self.alert_list.takeItem(self.alert_list.count() - 1)
        self.unread += 1
        self._update_bell()
        self.statusBar().showMessage(f"⚠ {title}", 15000)
        background = not self.isActiveWindow() or tab is not self.current_tab()
        if self.cfg["alerts_enabled"] and self.tray and background:
            icon = {"down": QSystemTrayIcon.MessageIcon.Critical,
                    "warning": QSystemTrayIcon.MessageIcon.Warning}.get(key, QSystemTrayIcon.MessageIcon.Information)
            self.tray.showMessage(title, message, icon, 10000)
            QApplication.alert(self, 0)

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _clear_alerts(self):
        self.alerts.clear()
        self.alert_list.clear()
        self.unread = 0
        self._update_bell()

    def _alerts_toggled(self, on):
        self.cfg["alerts_enabled"] = on
        self.cfg.save()

    def _logging_toggled(self, on):
        self.cfg["session_logging"] = on
        self.cfg.save()
        self._update_log_label()

    def _update_log_label(self):
        folder = self.cfg["log_dir"] or str(default_log_dir())
        self.log_label.setText(f"Folder: {folder}" + ("" if self.cfg["session_logging"] else "  (off)"))

    def _open_logs(self):
        folder = self.cfg["log_dir"] or str(default_log_dir())
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ============================================================= settings / theme
    def toggle_theme(self):
        self.cfg["dark_mode"] = not self.cfg["dark_mode"]
        self.cfg.save()
        self._apply_theme()

    def _apply_theme(self):
        apply_theme(QApplication.instance(), bool(self.cfg["dark_mode"]))
        self.theme_btn.setText("☀" if self.cfg["dark_mode"] else "☾")
        refresh_themed_widgets()
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            if isinstance(t, DeviceTab):
                t.refresh_theme()
                self._update_tab_icon(t)
        self._update_pill()
        self._update_bell()
        self._reload_devices()

    def open_settings(self):
        was_dark = bool(self.cfg["dark_mode"])
        if SettingsDialog(self.cfg, self).exec():
            if bool(self.cfg["dark_mode"]) != was_dark:
                self._apply_theme()
            self.alerts_on.setChecked(bool(self.cfg["alerts_enabled"]))
            self.logging_on.setChecked(bool(self.cfg["session_logging"]))
            self._update_log_label()
            for i in range(self.tabs.count()):
                t = self.tabs.widget(i)
                if isinstance(t, DeviceTab):
                    t.restart_timer(getattr(t, "paused", False))
                    t.refresh_theme()

    # ================================================================ close
    def closeEvent(self, e):
        open_tabs = [self.tabs.widget(i) for i in range(self.tabs.count())]
        live = [t for t in open_tabs if isinstance(t, DeviceTab) and t.state != DISCONNECTED]
        if live and QMessageBox.question(self, APP_NAME, f"Disconnect {len(live)} open session(s) and quit?") != \
                QMessageBox.StandardButton.Yes:
            e.ignore()
            return
        c = self.cfg
        c["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        c["bastion"] = self.bastion.text().strip()
        c["username"] = self.username.text().strip().upper()
        c["remember_password"] = self.remember.isChecked()
        c["use_device_creds"] = self.dev_creds.isChecked()
        if self.dev_user.text().strip():
            c["device_username"] = self.dev_user.text().strip()
            if self.remember.isChecked() and self.dev_pw.text():
                c.set_device_password(c["device_username"], self.dev_pw.text(), persist=True)
        if self.remember.isChecked() and self.password.text():
            c.set_password(c["username"], self.password.text(), persist=True)
        elif not self.remember.isChecked():
            c.delete_password(c["username"])
        c.save()
        for t in open_tabs:
            if isinstance(t, DeviceTab):
                t.shutdown()
        if self.tray:
            self.tray.hide()
        self.history.close()
        super().closeEvent(e)
