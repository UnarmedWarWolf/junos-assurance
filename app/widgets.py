"""Reusable widgets: cards, KPI tiles, health ring, sparkline, dashlet tables,
searchable/filterable output panels, the CLI console, and the small dialogs."""
import os
import re
import sys
import weakref

from PySide6.QtCore import QPointF, QRectF, QRegularExpression, QStringListModel, Qt, QTimer, Signal, QEvent
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QKeySequence, QPainter, QPainterPath, QPen,
                           QRegularExpressionValidator, QShortcut, QSyntaxHighlighter, QTextCharFormat,
                           QTextCursor, QTextDocument)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMenu, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QToolButton, QVBoxLayout,
                               QWidget)

from .theme import COLORS, STATUS_HEX, color_spans, status_key

_THEMED = weakref.WeakSet()       # widgets with a refresh_theme() method


def refresh_themed_widgets():
    for w in list(_THEMED):
        try:
            w.refresh_theme()
        except RuntimeError:       # C++ object already deleted
            pass


def mono_font(size=11):
    f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    if sys.platform == "win32":
        f.setFamilies(["Consolas", "Cascadia Mono", "Courier New", f.family()])
        size = max(8, size - 1)
    else:
        f.setFamilies(["Menlo", "SF Mono", "Consolas", "DejaVu Sans Mono", f.family()])
    f.setPointSize(size)
    return f


class Card(QFrame):
    """Rounded panel with a title row (DNA-Center style dashlet)."""

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


def section_label(text):
    lab = QLabel(text.upper())
    lab.setObjectName("Section")
    return lab


def chip(text, key=None):
    """Small rounded status pill (theme-aware at creation time)."""
    bg = {"up": "up_bg", "down": "down_bg", "warning": "warning_bg", "interface": "interface_bg"}.get(key, "neutral_bg")
    fg = {"up": "up", "down": "down", "warning": "warning_text", "interface": "interface"}.get(key, "muted")
    lab = QLabel(text)
    lab.setStyleSheet(f"background:{COLORS[bg]}; color:{COLORS[fg]}; border-radius:9px; padding:2px 9px;"
                      f"font-size:11px; font-weight:600;")
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


# =============================================================== health ring
def health_key(score):
    if score is None or score < 0:
        return None
    return "up" if score >= 90 else ("warning" if score >= 70 else "down")


def health_word(score):
    if score is None or score < 0:
        return "No data"
    return "Healthy" if score >= 90 else ("Fair" if score >= 70 else "Poor")


class HealthRing(QFrame):
    """DNA-Center style 0–100 health score ring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedWidth(190)
        self.setMinimumHeight(96)
        self.score = None
        self.detail = ""
        self.setToolTip("Overall health: link-down ports, optic levels and recent flaps")

    def set_score(self, score, detail=""):
        self.score, self.detail = score, detail
        self.setToolTip(f"Overall health score{(': ' + detail) if detail else ''}")
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.height() - 18, 78)
        r = QRectF(14, (self.height() - size) / 2, size, size)
        p.setPen(QPen(QColor(COLORS["neutral_bg"]), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 0, 360 * 16)
        key = health_key(self.score)
        if self.score is not None and self.score >= 0:
            p.setPen(QPen(QColor(STATUS_HEX[key]), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(r, 90 * 16, -int(360 * 16 * max(0, min(100, self.score)) / 100))
        f = QFont(self.font())
        f.setPointSizeF(max(12.0, f.pointSizeF() * 1.6))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(STATUS_HEX.get(key, COLORS["muted"])))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "–" if self.score is None or self.score < 0 else str(self.score))
        tx = r.right() + 12
        f2 = QFont(self.font())
        f2.setBold(True)
        f2.setPointSizeF(max(7.0, f2.pointSizeF() * 0.85))
        p.setFont(f2)
        p.setPen(QColor(COLORS["muted"]))
        p.drawText(QRectF(tx, r.top() + 6, self.width() - tx - 6, 16), Qt.AlignmentFlag.AlignLeft, "HEALTH")
        f3 = QFont(self.font())
        f3.setPointSizeF(max(9.0, f3.pointSizeF() * 1.15))
        f3.setBold(True)
        p.setFont(f3)
        p.setPen(QColor(STATUS_HEX.get(key, COLORS["muted"])))
        p.drawText(QRectF(tx, r.top() + 24, self.width() - tx - 6, 22), Qt.AlignmentFlag.AlignLeft,
                   health_word(self.score))


# ================================================================== sparkline
class Sparkline(QWidget):
    """Small Rx-over-time chart with the warning level drawn as a dashed line."""

    def __init__(self, parent=None, height=56):
        super().__init__(parent)
        self.setMinimumHeight(height)
        self.points = []          # [(ts, value)]
        self.warn = None
        self.alarm = None

    def set_series(self, points, warn=None, alarm=None):
        self.points = [(t, v) for t, v in points if v is not None]
        self.warn, self.alarm = warn, alarm
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        box = QRectF(2, 6, w - 44, h - 14)
        if len(self.points) < 2:
            p.setPen(QColor(COLORS["muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "History builds up as the app keeps polling" if not self.points else "1 sample so far")
            return
        ts = [t for t, _ in self.points]
        vs = [v for _, v in self.points]
        lo = min(vs + ([self.warn] if self.warn is not None else []))
        hi = max(vs)
        if hi - lo < 1:
            hi, lo = hi + 0.5, lo - 0.5
        t0, t1 = ts[0], ts[-1] if ts[-1] > ts[0] else ts[0] + 1

        def pt(t, v):
            return QPointF(box.left() + (t - t0) / (t1 - t0) * box.width(),
                           box.bottom() - (v - lo) / (hi - lo) * box.height())
        if self.warn is not None and lo <= self.warn <= hi:
            y = pt(t0, self.warn).y()
            p.setPen(QPen(QColor(COLORS["warning"]), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(box.left(), y), QPointF(box.right(), y))
        path = QPainterPath(pt(*self.points[0]))
        for t, v in self.points[1:]:
            path.lineTo(pt(t, v))
        last = vs[-1]
        col = COLORS["down"] if (self.alarm is not None and last < self.alarm) else \
            (COLORS["warning"] if (self.warn is not None and last < self.warn) else COLORS["accent"])
        p.setPen(QPen(QColor(col), 2))
        p.drawPath(path)
        p.setBrush(QColor(col))
        p.drawEllipse(pt(ts[-1], last), 3, 3)
        f = QFont(self.font())
        f.setPointSizeF(max(6.5, f.pointSizeF() - 2.5))
        p.setFont(f)
        p.setPen(QColor(COLORS["muted"]))
        p.drawText(QRectF(box.right() + 4, box.top() - 6, 40, 12), Qt.AlignmentFlag.AlignLeft, f"{hi:.1f}")
        p.drawText(QRectF(box.right() + 4, box.bottom() - 6, 40, 12), Qt.AlignmentFlag.AlignLeft, f"{lo:.1f}")


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
        """Cells may be plain values or (text, color_key) tuples."""
        self.rows = rows
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                forced = None
                if isinstance(val, tuple):
                    val, forced = val
                text = "" if val is None else str(val)
                item = QTableWidgetItem(text)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    item.setData(Qt.ItemDataRole.DisplayRole, val)
                key = forced or status_key(text)
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

    def plain_rows(self):
        return [[v[0] if isinstance(v, tuple) else v for v in row] for row in self.rows]

    def _dbl(self, r, _c):
        item = self.table.item(r, 0)
        if item:
            self.row_activated.emit(item.text())


# ============================================================ CLI highlighter
class CliHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self.extra = None           # optional regex to highlight (live filter)
        self.build()

    def build(self):
        self.formats = {}
        for key, hexcol in STATUS_HEX.items():
            f = QTextCharFormat()
            f.setForeground(QColor(hexcol))
            if key != "interface":
                f.setFontWeight(700)
            self.formats[key] = f
        self.hit = QTextCharFormat()
        self.hit.setBackground(QColor(COLORS["find_hit"]))

    def highlightBlock(self, text):
        for s, e, key in color_spans(text):
            self.setFormat(s, e - s, self.formats[key])
        if self.extra is not None:
            for m in self.extra.finditer(text):
                if m.end() > m.start():
                    self.setFormat(m.start(), m.end() - m.start(), self.hit)


class OutputView(QPlainTextEdit):
    """Read-only, color-highlighted, auto-scrolling text view."""

    def __init__(self, parent=None, max_blocks=50000):
        super().__init__(parent)
        self.setObjectName("Console")
        self.setReadOnly(True)
        self.setFont(mono_font(11))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setMaximumBlockCount(max_blocks)
        self.highlighter = CliHighlighter(self.document())
        _THEMED.add(self)

    def refresh_theme(self):
        self.highlighter.build()
        self.highlighter.rehighlight()

    def append_raw(self, text):
        sb = self.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        cur = QTextCursor(self.document())
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(text)
        if at_bottom:
            sb.setValue(sb.maximum())


def filter_regex(text):
    """Filter/search text -> compiled regex. 'a|b' works like Junos '| match'; otherwise plain text."""
    text = text.strip()
    if not text:
        return None
    try:
        if "|" in text or text.startswith("^") or text.endswith("$"):
            return re.compile(text, re.IGNORECASE)
    except re.error:
        pass
    return re.compile(re.escape(text), re.IGNORECASE)


class OutputPanel(QWidget):
    """OutputView + live line filter + Ctrl+F find bar."""

    def __init__(self, parent=None, max_blocks=50000):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedWidget()
        self.view = OutputView(max_blocks=max_blocks)
        self.fview = OutputView(max_blocks=max_blocks)
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.fview)
        lay.addWidget(self.stack, 1)

        # live filter (placed in the owner's title row)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter lines…  (a|b works like | match)")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setMaximumWidth(260)
        self.filter_edit.textChanged.connect(lambda _t: self._ftimer.start())
        self._ftimer = QTimer(self)
        self._ftimer.setSingleShot(True)
        self._ftimer.setInterval(250)
        self._ftimer.timeout.connect(self._apply_filter)

        # find bar
        self.findbar = QFrame()
        self.findbar.setObjectName("FindBar")
        fl = QHBoxLayout(self.findbar)
        fl.setContentsMargins(8, 4, 8, 4)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find…")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.textChanged.connect(self._find_changed)
        self.find_edit.returnPressed.connect(lambda: self.find_next(False))
        self.find_count = QLabel("")
        self.find_count.setObjectName("Muted")
        b_prev = QToolButton()
        b_prev.setText("▲")
        b_prev.setToolTip("Previous (Shift+Enter)")
        b_prev.clicked.connect(lambda: self.find_next(True))
        b_next = QToolButton()
        b_next.setText("▼")
        b_next.setToolTip("Next (Enter)")
        b_next.clicked.connect(lambda: self.find_next(False))
        b_close = QToolButton()
        b_close.setText("✕")
        b_close.clicked.connect(self.close_find)
        fl.addWidget(QLabel("Find"))
        fl.addWidget(self.find_edit, 1)
        fl.addWidget(self.find_count)
        fl.addWidget(b_prev)
        fl.addWidget(b_next)
        fl.addWidget(b_close)
        self.findbar.hide()
        lay.addWidget(self.findbar)
        self.find_edit.installEventFilter(self)

        sc = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(self.open_find)

    # ---------------------------------------------------------- content API
    def append(self, text):
        self.view.append_raw(text)
        if self.filter_edit.text().strip():
            self._ftimer.start()

    def setPlainText(self, text):
        self.view.setPlainText(text)
        self._apply_filter()

    def text(self):
        return self.view.toPlainText()

    def clear(self):
        self.view.clear()
        self.fview.clear()

    def active_view(self):
        return self.stack.currentWidget()

    # --------------------------------------------------------------- filter
    def _apply_filter(self):
        rx = filter_regex(self.filter_edit.text())
        if rx is None:
            self.view.highlighter.extra = None
            self.stack.setCurrentWidget(self.view)
            return
        lines = [ln for ln in self.view.toPlainText().split("\n") if rx.search(ln)]
        self.fview.highlighter.extra = rx
        self.fview.setPlainText("\n".join(lines) if lines else "(no matching lines)")
        self.fview.verticalScrollBar().setValue(self.fview.verticalScrollBar().maximum())
        self.stack.setCurrentWidget(self.fview)

    # ----------------------------------------------------------------- find
    def open_find(self):
        self.findbar.show()
        sel = self.active_view().textCursor().selectedText()
        if sel:
            self.find_edit.setText(sel)
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def close_find(self):
        self.findbar.hide()
        for v in (self.view, self.fview):
            v.setExtraSelections([])

    def eventFilter(self, obj, ev):
        if obj is self.find_edit and ev.type() == QEvent.Type.KeyPress:
            if ev.key() == Qt.Key.Key_Escape:
                self.close_find()
                return True
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.find_next(True)
                return True
        return super().eventFilter(obj, ev)

    def _find_changed(self, text):
        v = self.active_view()
        sels = []
        count = 0
        if text:
            doc = v.document()
            cur = QTextCursor(doc)
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(COLORS["find_hit"]))
            while True:
                cur = doc.find(text, cur)
                if cur.isNull():
                    break
                count += 1
                if count <= 2000:
                    s = QTextEdit.ExtraSelection()
                    s.cursor = cur
                    s.format = fmt
                    sels.append(s)
        v.setExtraSelections(sels)
        self.find_count.setText(f"{count} match{'es' if count != 1 else ''}" if text else "")
        if text:
            v.moveCursor(QTextCursor.MoveOperation.Start)
            self.find_next(False)

    def find_next(self, backward=False):
        text = self.find_edit.text()
        if not text:
            return
        v = self.active_view()
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if not v.find(text, flags):
            v.moveCursor(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
            v.find(text, flags)


# =========================================================== CLI completion
BASE_COMMANDS = [
    "show interfaces terse", "show interfaces descriptions", "show interfaces diagnostics optics",
    "show interfaces extensive", "show interfaces statistics", "show chassis hardware", "show chassis alarms",
    "show chassis environment", "show chassis fpc", "show chassis pic fpc-slot", "show chassis routing-engine",
    "show chassis craft-interface", "show system uptime", "show system users", "show system alarms",
    "show system storage", "show system commit", "show system processes extensive", "show version",
    "show lldp neighbors", "show ethernet-switching table", "show vlans", "show route", "show route summary",
    "show route forwarding-table summary", "show bgp summary", "show ospf neighbor", "show log messages",
    "show arp", "show lacp interfaces", "show configuration", "show configuration interfaces",
    "show configuration | display set", "monitor interface", "monitor traffic interface",
    "clear interfaces statistics", "request support information", "ping", "traceroute", "configure",
    "commit check", "commit confirmed 5", "commit", "rollback", "exit", "quit", "op up-down.py flap all",
    "| no-more", "| match", "| except", "| last", "| count", "| display set",
]


class CompletingLineEdit(QLineEdit):
    """Command line with ↑/↓ history and Tab completion of commands and interface names."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history, self.idx = [], 0
        self.just_chosen = False
        self.phrases = list(BASE_COMMANDS)
        self.interfaces = []
        self.completer = QCompleter(self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setMaxVisibleItems(12)
        self.model = QStringListModel(self)
        self.completer.setModel(self.model)
        self.completer.activated.connect(self._chosen)

    def add_phrases(self, phrases):
        for p in phrases:
            p = p.strip()
            if p and p not in self.phrases:
                self.phrases.append(p)

    def set_interfaces(self, names):
        self.interfaces = list(names)

    def push(self, line):
        if line and (not self.history or self.history[-1] != line):
            self.history.append(line)
        self.idx = len(self.history)

    def _chosen(self, text):
        # Enter in the popup is also forwarded to the line edit; don't run the command on that Enter.
        self.just_chosen = True
        QTimer.singleShot(0, lambda: setattr(self, "just_chosen", False))
        self.setText(text)
        self.setCursorPosition(len(text))

    def candidates(self, text):
        m = re.search(r"(\S*)$", text)
        token, head = m.group(1), text[:m.start(1)]
        if head.strip() and token and re.match(r"^[a-z]{1,4}(-[\d/:]*)?$", token, re.I):
            iface = [head + i for i in self.interfaces if i.lower().startswith(token.lower())]
            if iface:
                return iface
        low = text.lower()
        return [p for p in self.phrases if p.lower().startswith(low) and p.lower() != low]

    def complete_now(self):
        text = self.text()
        cands = self.candidates(text)
        if not cands:
            return
        if len(cands) == 1:
            self.setText(cands[0] + ("" if cands[0].endswith(" ") else " "))
            return
        common = os.path.commonprefix([c.lower() for c in cands])
        if len(common) > len(text):
            self.setText(cands[0][:len(common)])
        self.model.setStringList(cands[:60])
        self.completer.setCompletionPrefix(self.text())
        self.completer.complete()

    def event(self, e):
        if e.type() == QEvent.Type.KeyPress and e.key() == Qt.Key.Key_Tab:
            self.complete_now()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if self.completer.popup().isVisible() and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter,
                                                               Qt.Key.Key_Up, Qt.Key.Key_Down):
            e.ignore()
            return
        if e.key() == Qt.Key.Key_Up and self.history:
            self.idx = max(0, self.idx - 1)
            self.setText(self.history[self.idx])
            return
        if e.key() == Qt.Key.Key_Down and self.history:
            self.idx = min(len(self.history), self.idx + 1)
            self.setText(self.history[self.idx] if self.idx < len(self.history) else "")
            return
        super().keyPressEvent(e)


# ================================================================ CLI console
class CliConsole(Card):
    command_entered = Signal(str)
    ctrl_c = Signal()
    save_requested = Signal(str)   # 'docx' or 'xlsx'
    explain_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("CLI", parent)
        self.prompt_badge = QLabel("not connected")
        self.prompt_badge.setObjectName("Badge")
        self.add_title_widget(self.prompt_badge)
        self.panel = OutputPanel()
        self.add_title_widget(self.panel.filter_edit)
        b_explain = QPushButton("Explain")
        b_explain.setToolTip("Explain the last command's output in plain English")
        b_explain.clicked.connect(lambda: self.explain_requested.emit())
        b_find = QToolButton()
        b_find.setObjectName("Flat")
        b_find.setText("Find")
        b_find.setToolTip("Find in output (Ctrl+F)")
        b_find.clicked.connect(self.panel.open_find)
        b_ctrl = QPushButton("Ctrl+C")
        b_ctrl.setToolTip("Interrupt the running command")
        b_ctrl.clicked.connect(lambda: self.ctrl_c.emit())
        b_clear = QToolButton()
        b_clear.setObjectName("Flat")
        b_clear.setText("Clear")
        b_clear.clicked.connect(lambda: self.panel.clear())
        b_save = QToolButton()
        b_save.setObjectName("Flat")
        b_save.setText("Save ▾")
        b_save.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(b_save)
        m.addAction("Save as Word document (.docx)…", lambda: self.save_requested.emit("docx"))
        m.addAction("Save as Excel workbook (.xlsx)…", lambda: self.save_requested.emit("xlsx"))
        b_save.setMenu(m)
        for w in (b_explain, b_find, b_ctrl, b_clear, b_save):
            self.add_title_widget(w)

        self.input = CompletingLineEdit()
        self.input.setObjectName("CliInput")
        self.input.setFont(mono_font(12))
        self.input.setPlaceholderText("Type any Junos command and press Enter   (Tab completes · ↑/↓ history · "
                                      "end with ? for help · Ctrl+F find)")
        self.input.returnPressed.connect(self._enter)
        frame = QFrame()
        frame.setObjectName("Boxed")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        fl.addWidget(self.panel, 1)
        fl.addWidget(self.input)
        self.body.addWidget(frame, 1)
        self.outer.setContentsMargins(10, 10, 10, 10)

    @property
    def view(self):
        return self.panel.view

    def _enter(self):
        if self.input.completer.popup().isVisible() or self.input.just_chosen:
            self.input.just_chosen = False
            return
        line = self.input.text()
        self.input.push(line)
        self.input.clear()
        self.command_entered.emit(line)

    def append(self, text):
        self.panel.append(text)

    def set_prompt(self, prompt):
        self.prompt_badge.setText(prompt or "not connected")

    def text(self):
        return self.panel.text()


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
        info = QLabel(message or "Your code is added to the end of your saved password and sent to the jump host. "
                                 "Codes refresh every 30 seconds, so enter the one showing now.")
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

    def __init__(self, cmd, interfaces=None, parent=None, preset=None):
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
                w.addItems(list(interfaces or []))
                w.setCurrentText((preset or {}).get("interface", ""))
                w.lineEdit().setPlaceholderText(p.example)
                comp = QCompleter(list(interfaces or []), w)
                comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                comp.setFilterMode(Qt.MatchFlag.MatchContains)
                w.setCompleter(comp)
                getter = w.currentText
            else:
                w = QLineEdit((preset or {}).get(p.name, ""))
                w.setPlaceholderText(p.example)
                getter = w.text
            self.inputs[p.name] = getter
            lay.addWidget(w)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setFont(mono_font(10))
        self.preview.setObjectName("Muted")
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


class InterfacePickDialog(QDialog):
    """Pick an interface (used to start a playbook)."""

    def __init__(self, title, description, interfaces, parent=None, preset=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        t = QLabel(title)
        t.setObjectName("CardTitle")
        lay.addWidget(t)
        d = QLabel(description)
        d.setWordWrap(True)
        d.setObjectName("Muted")
        lay.addWidget(d)
        lay.addWidget(field_label("Interface"))
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.addItems(list(interfaces))
        self.combo.setCurrentText(preset)
        self.combo.lineEdit().setPlaceholderText("xe-0/0/0")
        comp = QCompleter(list(interfaces), self.combo)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        self.combo.setCompleter(comp)
        lay.addWidget(self.combo)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok = bb.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Run playbook")
        ok.setObjectName("Primary")
        bb.accepted.connect(lambda: self.value() and self.accept())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def value(self):
        return self.combo.currentText().strip()


# ============================================================ Settings dialog
class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Settings")
        self.setMinimumWidth(720)
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
        self.domain.setToolTip("Added to switch names that have no dot.")
        self.login_tpl = QLineEdit(cfg["bastion_login_template"])
        self.login_tpl.setToolTip("Login name sent to the jump host. {username} = your P-Number.")
        self.hop_tpl = QLineEdit(cfg["hop_template"])
        self.hop_tpl.setToolTip("Command typed on the bastion to reach the switch. {hostname} = switch name.")
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
        f1.addRow("Hop command", self.hop_tpl)
        f1.addRow("Command timeout", self.timeout)
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
        self.mon_cmds = {}
        for key, label in (("terse", "Admin/Link command"), ("descriptions", "Descriptions command"),
                           ("flaps", "Flap command"), ("optics", "Optics command")):
            e = QLineEdit(cfg["monitor_commands"].get(key, ""))
            e.setFont(mono_font(10))
            self.mon_cmds[key] = e
            f2.addRow(label, e)
        tabs.addTab(w2, "Monitoring")

        # --- history & alerts
        w3 = QWidget()
        f3 = QFormLayout(w3)
        self.alerts = QCheckBox("Show desktop notifications for flaps, ports going down and weak optics")
        self.alerts.setChecked(bool(cfg["alerts_enabled"]))
        self.hist_days = QSpinBox()
        self.hist_days.setRange(1, 365)
        self.hist_days.setSuffix(" days")
        self.hist_days.setValue(int(cfg["history_days"]))
        self.trend_hours = QSpinBox()
        self.trend_hours.setRange(1, 24 * 14)
        self.trend_hours.setSuffix(" h")
        self.trend_hours.setValue(int(cfg["trend_hours"]))
        self.trend_db = QDoubleSpinBox()
        self.trend_db.setRange(0.5, 20)
        self.trend_db.setSuffix(" dB")
        self.trend_db.setValue(float(cfg["trend_alert_db"]))
        f3.addRow("", self.alerts)
        f3.addRow("Keep light history for", self.hist_days)
        f3.addRow("Rx trend window", self.trend_hours)
        f3.addRow("Flag Rx drops larger than", self.trend_db)
        tabs.addTab(w3, "History && Alerts")

        # --- logging & appearance
        w4 = QWidget()
        f4 = QFormLayout(w4)
        self.logging = QCheckBox("Save every session to a log file automatically")
        self.logging.setChecked(bool(cfg["session_logging"]))
        from .session_log import default_log_dir
        self.log_dir = QLineEdit(cfg["log_dir"] or str(default_log_dir()))
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.log_dir, 1)
        row.addWidget(b)
        self.dark = QCheckBox("Dark mode")
        self.dark.setChecked(bool(cfg["dark_mode"]))
        f4.addRow("", self.logging)
        f4.addRow("Log folder", row)
        f4.addRow("", self.dark)
        tabs.addTab(w4, "Logs && Appearance")

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose log folder", self.log_dir.text())
        if d:
            self.log_dir.setText(d)

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
        c["alerts_enabled"] = self.alerts.isChecked()
        c["history_days"] = self.hist_days.value()
        c["trend_hours"] = self.trend_hours.value()
        c["trend_alert_db"] = self.trend_db.value()
        c["session_logging"] = self.logging.isChecked()
        c["log_dir"] = self.log_dir.text().strip()
        c["dark_mode"] = self.dark.isChecked()
        c.save()
        self.accept()
