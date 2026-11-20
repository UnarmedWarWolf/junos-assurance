"""Reusable widgets: cards, KPI tiles, dashlet tables, CLI console and dialogs."""
from PySide6.QtCore import Qt, Signal, QTimer, QRegularExpression
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QSyntaxHighlighter, QTextCharFormat,
                           QTextCursor, QRegularExpressionValidator)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget, QCompleter, QTabWidget)

from .theme import COLORS, STATUS_HEX, color_spans, status_key


def mono_font(size=11):
    import sys
    f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    if sys.platform == "win32":
        f.setFamilies(["Consolas", "Cascadia Mono", "Courier New", f.family()])
        size = max(8, size - 1)
    else:
        f.setFamilies(["Menlo", "SF Mono", "Consolas", "DejaVu Sans Mono", f.family()])
    f.setPointSize(size)
    return f


class Card(QFrame):
    """White rounded panel with a title row (DNA-Center style dashlet)."""

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(14, 12, 14, 12)
        self.outer.setSpacing(8)
        self.title_row = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.title_row.addWidget(self.title_label)
        self.title_row.addStretch(1)
        self.outer.addLayout(self.title_row)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self.outer.addLayout(self.body)

    def add_title_widget(self, w):
        self.title_row.addWidget(w)


def field_label(text):
    lab = QLabel(text)
    lab.setObjectName("FieldLabel")
    return lab


# =================================================================== KPI tile
class KpiTile(QFrame):
    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 14, 0)
        self.bar = QFrame()
        self.bar.setFixedWidth(5)
        lay.addWidget(self.bar)
        col = QVBoxLayout()
        col.setContentsMargins(10, 10, 0, 10)
        col.setSpacing(2)
        self.t = QLabel(title.upper())
        self.t.setObjectName("KpiTitle")
        self.v = QLabel("–")
        self.v.setObjectName("KpiValue")
        self.s = QLabel(subtitle)
        self.s.setObjectName("Muted")
        col.addWidget(self.t)
        col.addWidget(self.v)
        col.addWidget(self.s)
        lay.addLayout(col, 1)
        self.set_value("–", None, None)

    def set_value(self, value, subtitle="", key=None):
        color = STATUS_HEX.get(key, COLORS["muted"]) if key else COLORS["border"]
        self.bar.setStyleSheet(f"background:{color}; border-top-left-radius:6px; border-bottom-left-radius:6px;")
        self.v.setText(str(value))
        self.v.setStyleSheet(f"color:{STATUS_HEX.get(key, COLORS['text'])};")
        if subtitle is not None:
            self.s.setText(subtitle)


# ============================================================== Dashlet table
class DashletTable(Card):
    row_activated = Signal(str)   # interface name double-clicked

    def __init__(self, title, headers, empty_text="No data yet", parent=None):
        super().__init__(title, parent)
        self.headers = headers
        self.empty_text = empty_text
        self.badge = QLabel("0")
        self.badge.setObjectName("Badge")
        self.add_title_widget(self.badge)
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.cellDoubleClicked.connect(self._dbl)
        self.empty = QLabel(empty_text)
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.table, 1)
        self.body.addWidget(self.empty)
        self.rows = []

    def set_rows(self, rows, empty_text=None):
        self.rows = rows
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                text = "" if val is None else str(val)
                item = QTableWidgetItem(text)
                if isinstance(val, (int, float)):
                    item.setData(Qt.ItemDataRole.DisplayRole, val)
                key = status_key(text)
                if key:
                    item.setForeground(QColor(STATUS_HEX[key]))
                    if key != "interface":
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.badge.setText(str(len(rows)))
        self.empty.setText(empty_text or self.empty_text)
        self.empty.setVisible(not rows)

    def _dbl(self, r, _c):
        item = self.table.item(r, 0)
        if item:
            self.row_activated.emit(item.text())


# ============================================================ CLI highlighter
class CliHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self.formats = {}
        for key, hexcol in STATUS_HEX.items():
            f = QTextCharFormat()
            f.setForeground(QColor(hexcol))
            if key != "interface":
                f.setFontWeight(700)
            self.formats[key] = f

    def highlightBlock(self, text):
        for s, e, key in color_spans(text):
            self.setFormat(s, e - s, self.formats[key])


class HistoryLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.history, self.idx = [], 0

    def push(self, line):
        if line and (not self.history or self.history[-1] != line):
            self.history.append(line)
        self.idx = len(self.history)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Up and self.history:
            self.idx = max(0, self.idx - 1)
            self.setText(self.history[self.idx])
            return
        if e.key() == Qt.Key.Key_Down and self.history:
            self.idx = min(len(self.history), self.idx + 1)
            self.setText(self.history[self.idx] if self.idx < len(self.history) else "")
            return
        super().keyPressEvent(e)


class OutputView(QPlainTextEdit):
    """Read-only, colour-highlighted, auto-scrolling text view."""

    def __init__(self, parent=None, max_blocks=50000):
        super().__init__(parent)
        self.setObjectName("Console")
        self.setReadOnly(True)
        self.setFont(mono_font(11))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setMaximumBlockCount(max_blocks)
        self.highlighter = CliHighlighter(self.document())

    def append_raw(self, text):
        sb = self.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        cur = QTextCursor(self.document())
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(text)
        if at_bottom:
            sb.setValue(sb.maximum())


class CliConsole(Card):
    command_entered = Signal(str)
    ctrl_c = Signal()
    save_requested = Signal(str)   # 'docx' or 'xlsx'

    def __init__(self, parent=None):
        super().__init__("CLI", parent)
        self.prompt_badge = QLabel("not connected")
        self.prompt_badge.setObjectName("Badge")
        self.add_title_widget(self.prompt_badge)
        b_ctrl = QPushButton("Ctrl+C")
        b_ctrl.setToolTip("Interrupt the running command")
        b_ctrl.clicked.connect(lambda: self.ctrl_c.emit())
        b_clear = QPushButton("Clear")
        b_clear.clicked.connect(lambda: self.view.clear())
        b_save = QToolButton()
        b_save.setText("Save CLI ▾")
        b_save.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(b_save)
        m.addAction("Save as Word document (.docx)…", lambda: self.save_requested.emit("docx"))
        m.addAction("Save as Excel workbook (.xlsx)…", lambda: self.save_requested.emit("xlsx"))
        b_save.setMenu(m)
        for w in (b_ctrl, b_clear, b_save):
            self.add_title_widget(w)

        self.view = OutputView()
        self.input = HistoryLineEdit()
        self.input.setObjectName("CliInput")
        self.input.setFont(mono_font(12))
        self.input.setPlaceholderText("Type any Junos command and press Enter  (↑/↓ history, end with ? for help)")
        self.input.returnPressed.connect(self._enter)
        frame = QFrame()
        frame.setStyleSheet(f"QFrame{{border:1px solid {COLORS['border']}; border-radius:4px;}}")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        fl.addWidget(self.view, 1)
        fl.addWidget(self.input)
        self.body.addWidget(frame, 1)
        self.outer.setContentsMargins(10, 10, 10, 10)

    def _enter(self):
        line = self.input.text()
        self.input.push(line)
        self.input.clear()
        self.command_entered.emit(line)

    def append(self, text):
        self.view.append_raw(text)

    def set_prompt(self, prompt):
        self.prompt_badge.setText(prompt or "not connected")

    def text(self):
        return self.view.toPlainText()


# ================================================================ VIP dialog
class VipDialog(QDialog):
    """Quick token entry – opens focused, Enter submits."""

    def __init__(self, parent=None, message="", need_password=False, password="", allow_empty=False):
        super().__init__(parent)
        self.allow_empty = allow_empty
        self.setWindowTitle("VIP Access")
        self.setModal(True)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        title = QLabel("Enter your VIP security code")
        title.setObjectName("CardTitle")
        lay.addWidget(title)
        info = QLabel(message or "Your code is appended to your saved password and sent to the bastion. "
                                 "Codes refresh every 30 seconds – enter the one showing now.")
        info.setWordWrap(True)
        info.setObjectName("Muted")
        lay.addWidget(info)
        self.pw = None
        if need_password:
            lay.addWidget(field_label("Password"))
            self.pw = QLineEdit(password)
            self.pw.setEchoMode(QLineEdit.EchoMode.Password)
            lay.addWidget(self.pw)
        lay.addWidget(field_label("VIP token"))
        self.token = QLineEdit()
        self.token.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,8}"), self))
        self.token.setMaxLength(8)
        self.token.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = mono_font(22)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 6)
        self.token.setFont(f)
        self.token.setPlaceholderText("••••••")
        lay.addWidget(self.token)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok = bb.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Connect")
        ok.setObjectName("Primary")
        ok.setDefault(True)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        QTimer.singleShot(0, (self.pw if (self.pw and not password) else self.token).setFocus)

    def _accept(self):
        if not self.token.text().strip() and not self.allow_empty:
            self.token.setFocus()
            return
        self.accept()

    def value(self):
        return self.token.text().strip()

    def password(self):
        return self.pw.text() if self.pw else None


# ============================================================ Param dialog
class ParamDialog(QDialog):
    """Asks for command parameters, with a 'Run as is' bypass when all are optional."""

    def __init__(self, cmd, interfaces=None, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.bypassed = False
        self.setWindowTitle(cmd.name)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        t = QLabel(cmd.name)
        t.setObjectName("CardTitle")
        lay.addWidget(t)
        d = QLabel(cmd.description)
        d.setWordWrap(True)
        d.setObjectName("Muted")
        lay.addWidget(d)
        self.inputs = {}
        for p in cmd.params:
            lab = QLabel(f"<b>{p.label}</b>" + ("" if not p.optional else
                                                 f" <span style='color:{COLORS['muted']}'>(optional)</span>"))
            lay.addWidget(lab)
            desc = QLabel(p.description)
            desc.setWordWrap(True)
            desc.setObjectName("Muted")
            lay.addWidget(desc)
            if p.name == "interface":
                w = QComboBox()
                w.setEditable(True)
                w.addItems(sorted(interfaces or []))
                w.setCurrentText("")
                w.lineEdit().setPlaceholderText(p.example)
                comp = QCompleter(sorted(interfaces or []), w)
                comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                comp.setFilterMode(Qt.MatchFlag.MatchContains)
                w.setCompleter(comp)
                getter = w.currentText
            else:
                w = QLineEdit()
                w.setPlaceholderText(p.example)
                getter = w.text
            self.inputs[p.name] = getter
            lay.addWidget(w)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setFont(mono_font(10))
        self.preview.setStyleSheet(f"color:{COLORS['muted']}; padding-top:6px;")
        lay.addWidget(self.preview)
        row = QHBoxLayout()
        if cmd.can_bypass:
            by = QPushButton("Run as is (skip)")
            by.setToolTip("Run the command without the optional parameters")
            by.clicked.connect(self._bypass)
            row.addWidget(by)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        run = QPushButton("Run")
        run.setObjectName("Primary")
        run.setDefault(True)
        run.clicked.connect(self._run)
        row.addWidget(cancel)
        row.addWidget(run)
        lay.addLayout(row)
        self.error = QLabel()
        self.error.setStyleSheet(f"color:{COLORS['down']};")
        lay.addWidget(self.error)
        t = QTimer(self)
        t.timeout.connect(self._update_preview)
        t.start(300)
        self._update_preview()

    def values(self):
        if self.bypassed:
            return {}
        return {k: g() for k, g in self.inputs.items()}

    def _update_preview(self):
        from .commands import render
        try:
            self.preview.setText("› " + render(self.cmd, self.values()))
        except ValueError:
            self.preview.setText("› " + self.cmd.template)

    def _bypass(self):
        self.bypassed = True
        self.accept()

    def _run(self):
        from .commands import render
        try:
            render(self.cmd, self.values())
        except ValueError as e:
            self.error.setText(str(e))
            return
        self.accept()


# ============================================================ Settings dialog
class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Settings")
        self.setMinimumWidth(700)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # --- connection
        w1 = QWidget()
        f1 = QFormLayout(w1)
        self.mode = QComboBox()
        self.mode.addItem("Automatic – tunnel if the jump host allows it, otherwise use its shell", "jump")
        self.mode.addItem("Bastion shell – type an ssh command on the bastion", "shell")
        self.mode.setCurrentIndex(max(0, self.mode.findData(cfg["connection_mode"])))
        self.domain = QLineEdit(cfg["device_domain"])
        self.domain.setPlaceholderText("optional, e.g. net.example.com")
        self.domain.setToolTip("Added to switch names that have no dot, so 'qfx-01' becomes 'qfx-01.net.example.com'.\n"
                               "Leave blank if the jump host resolves short names itself.")
        self.login_tpl = QLineEdit(cfg["bastion_login_template"])
        self.login_tpl.setToolTip("Login name sent to the jump host. {username} = your P-Number.\n"
                                  "Examples: {username}   DOMAIN\\{username}   {username}@jump.example.com")
        self.hop_tpl = QLineEdit(cfg["hop_template"])
        self.hop_tpl.setToolTip("Bastion-shell mode only: command typed on the bastion to reach the switch.")
        self.switch_auth = QComboBox()
        self.switch_auth.addItem("Password only (ask for a VIP code if it is rejected)", "password")
        self.switch_auth.addItem("Password + a new VIP code", "password_vip")
        self.switch_auth.setCurrentIndex(max(0, self.switch_auth.findData(cfg["switch_auth"])))
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 3600)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(int(cfg["command_timeout"]))
        f1.addRow("Connection method", self.mode)
        f1.addRow("Jump host login name", self.login_tpl)
        f1.addRow("Switch domain suffix", self.domain)
        f1.addRow("Switch login", self.switch_auth)
        f1.addRow("Hop command (shell mode)", self.hop_tpl)
        f1.addRow("Command timeout", self.timeout)
        self.mode.currentIndexChanged.connect(
            lambda _=0: self.hop_tpl.setEnabled(self.mode.currentData() == "shell"))
        self.hop_tpl.setEnabled(self.mode.currentData() == "shell")
        tabs.addTab(w1, "Connection")

        # --- monitoring
        w2 = QWidget()
        f2 = QFormLayout(w2)
        self.mon_on = QCheckBox("Run health checks in the background")
        self.mon_on.setChecked(bool(cfg["monitor_enabled"]))
        self.interval = QSpinBox()
        self.interval.setRange(15, 3600)
        self.interval.setSuffix(" s")
        self.interval.setValue(int(cfg["poll_interval"]))
        self.flap_hours = QSpinBox()
        self.flap_hours.setRange(1, 24 * 30)
        self.flap_hours.setSuffix(" h")
        self.flap_hours.setValue(int(cfg["flap_window_hours"]))
        self.rx_warn = QDoubleSpinBox()
        self.rx_warn.setRange(-40, 10)
        self.rx_warn.setSuffix(" dBm")
        self.rx_warn.setValue(float(cfg["rx_warn_default"]))
        self.rx_alarm = QDoubleSpinBox()
        self.rx_alarm.setRange(-40, 10)
        self.rx_alarm.setSuffix(" dBm")
        self.rx_alarm.setValue(float(cfg["rx_alarm_default"]))
        f2.addRow("", self.mon_on)
        f2.addRow("Refresh every", self.interval)
        f2.addRow("Recent-flap window", self.flap_hours)
        f2.addRow("Rx warning (fallback)", self.rx_warn)
        f2.addRow("Rx critical (fallback)", self.rx_alarm)
        note = QLabel("Optic thresholds reported by each transceiver are used first; these are fallbacks.")
        note.setObjectName("Muted")
        f2.addRow("", note)
        self.mon_cmds = {}
        for key, label in (("terse", "Admin/Link command"), ("descriptions", "Descriptions command"),
                           ("flaps", "Flap command"), ("optics", "Optics command")):
            e = QLineEdit(cfg["monitor_commands"].get(key, ""))
            e.setFont(mono_font(10))
            self.mon_cmds[key] = e
            f2.addRow(label, e)
        tabs.addTab(w2, "Monitoring")

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _save(self):
        c = self.cfg
        c["bastion_login_template"] = self.login_tpl.text().strip() or "{username}"
        c["connection_mode"] = self.mode.currentData()
        c["device_domain"] = self.domain.text().strip().lstrip(".")
        c["hop_template"] = self.hop_tpl.text().strip()
        c["switch_auth"] = self.switch_auth.currentData()
        c["command_timeout"] = self.timeout.value()
        c["monitor_enabled"] = self.mon_on.isChecked()
        c["poll_interval"] = self.interval.value()
        c["flap_window_hours"] = self.flap_hours.value()
        c["rx_warn_default"] = self.rx_warn.value()
        c["rx_alarm_default"] = self.rx_alarm.value()
        mc = dict(c["monitor_commands"])
        for k, e in self.mon_cmds.items():
            if e.text().strip():
                mc[k] = e.text().strip()
        c["monitor_commands"] = mc
        c.save()
        self.accept()
