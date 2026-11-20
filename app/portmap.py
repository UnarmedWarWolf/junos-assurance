"""Front-panel port map, optical light gauge and the Interface 360 side panel."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QToolButton, QToolTip, QVBoxLayout, QWidget)

from .parsers import fmt_bps, split_port
from .theme import COLORS
from .widgets import OutputView

# Port states -> fill colours
STATE_FILL = {
    "up": "#34A853",        # link up, healthy
    "warning": "#E0A800",   # link up but optics warning/critical
    "down": "#D0271D",      # admin up, link down
    "disabled": "#C5CDD6",  # admin down
    "unknown": "#FFFFFF",   # seen but no state yet
}
STATE_LABEL = {"up": "Up", "warning": "Optics warning", "down": "Admin up · Link down",
               "disabled": "Disabled", "unknown": "Unknown"}
DOT_COLOR = {"critical": "#D0271D", "warning": "#E0A800"}


def chip(text, key=None):
    """Small rounded status pill."""
    colors = {"up": ("#E7F6EC", COLORS["up"]), "down": ("#FCE9E8", COLORS["down"]),
              "warning": ("#FFF6DB", "#9A7400"), "interface": ("#F1EAFB", COLORS["interface"]),
              None: ("#EEF1F4", COLORS["muted"])}
    bg, fg = colors.get(key, colors[None])
    lab = QLabel(text)
    lab.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:9px; padding:2px 9px; "
                      f"font-size:11px; font-weight:600;")
    return lab


def legend_widget():
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    for st in ("up", "warning", "down", "disabled"):
        sw = QLabel()
        sw.setFixedSize(12, 10)
        sw.setStyleSheet(f"background:{STATE_FILL[st]}; border-radius:2px; border:1px solid #9AA5B1;")
        lay.addWidget(sw)
        t = QLabel(STATE_LABEL[st].replace("Admin up · ", ""))
        t.setObjectName("Muted")
        lay.addWidget(t)
    dot = QLabel("●")
    dot.setStyleSheet(f"color:{DOT_COLOR['critical']}; font-size:11px;")
    lay.addWidget(dot)
    t = QLabel("Recent flap")
    t.setObjectName("Muted")
    lay.addWidget(t)
    return w


# ===================================================================== port map
def layout_ports(names, PW=26, PH=20, GX=4, GY=6):
    """Pure layout: returns ([(x, y, w, h, name, number_label, row)], [(y, group_label)], width, height).
    Each FPC/PIC is a block; ports run left->right in pairs (even top, odd bottom) like a faceplate,
    with a small gap every 12 ports and a wider gap where the port type changes (xe -> et uplinks)."""
    groups = {}
    for name in names:
        sp = split_port(name)
        if sp:
            typ, fpc, pic, port, ch = sp
            groups.setdefault((fpc, pic), []).append((port, -1 if ch is None else ch, typ, name))
    out, labels, y, maxx = [], [], 6, 0
    for key in sorted(groups):
        labels.append((y, f"FPC {key[0]}  ·  PIC {key[1]}"))
        top = y + 16 + 12
        i, extra, prev_type = 0, 0, None
        for port, ch, typ, name in sorted(groups[key]):
            if prev_type is not None and typ != prev_type:
                if i % 2:
                    i += 1
                extra += 16
            elif i and i % 2 == 0 and (i // 2) % 6 == 0:
                extra += 8
            col, row = i // 2, i % 2
            x = 10 + col * (PW + GX) + extra
            out.append((x, top + row * (PH + GY), PW, PH, name, f"{port}:{ch}" if ch >= 0 else str(port), row))
            maxx = max(maxx, x + PW)
            prev_type = typ
            i += 1
        y = top + 2 * PH + GY + 14 + 12
    return out, labels, maxx + 14, y


class PortMapWidget(QWidget):
    """Draws ports like a switch faceplate: even ports top row, odd ports bottom row, per FPC/PIC."""
    port_clicked = Signal(str)

    PW, PH, GX, GY = 26, 20, 4, 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.ports = {}            # name -> {"state":..., "dot":..., "tip":...}
        self.rects = []            # (QRectF, name, number_label, row)
        self.labels = []           # (y, text)
        self.selected = None
        self.hover = None
        self.setMinimumHeight(90)

    def set_ports(self, ports: dict):
        self.ports = ports
        self._relayout()
        self.update()

    def set_selected(self, name):
        self.selected = name
        self.update()

    def _relayout(self):
        items, labels, w, h = layout_ports(self.ports, self.PW, self.PH, self.GX, self.GY)
        self.rects = [(QRectF(x, y, pw, ph), name, num, row) for x, y, pw, ph, name, num, row in items]
        self.labels = labels
        self.setMinimumWidth(int(w) if items else 200)
        self.setMinimumHeight(int(h) if items else 90)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.rects:
            p.setPen(QColor(COLORS["muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Connect to a switch to see its ports")
            return
        lf = QFont(self.font())
        lf.setPointSizeF(max(7.0, lf.pointSizeF() - 1))
        lf.setBold(True)
        p.setFont(lf)
        p.setPen(QColor(COLORS["muted"]))
        for y, text in self.labels:
            p.drawText(QRectF(10, y, 400, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        nf = QFont(self.font())
        nf.setPointSizeF(max(6.5, nf.pointSizeF() - 2.5))
        for r, name, num, row in self.rects:
            info = self.ports.get(name, {})
            st = info.get("state", "unknown")
            fill = QColor(STATE_FILL[st])
            if name == self.hover:
                fill = fill.lighter(112)
            p.setPen(QPen(QColor("#7D8B99") if st != "unknown" else QColor("#B6C0CA"), 1))
            p.setBrush(fill)
            p.drawRoundedRect(r, 3, 3)
            # inner "cage" line for a bit of realism
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            p.drawLine(QPointF(r.left() + 5, r.bottom() - 5), QPointF(r.right() - 5, r.bottom() - 5))
            if name == self.selected:
                p.setPen(QPen(QColor(COLORS["accent"]), 2.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(-2.5, -2.5, 2.5, 2.5), 4, 4)
            dot = info.get("dot")
            if dot:
                p.setPen(QPen(QColor("#FFFFFF"), 1.2))
                p.setBrush(QColor(DOT_COLOR[dot]))
                p.drawEllipse(QPointF(r.right() - 1, r.top() + 1), 4.2, 4.2)
            p.setFont(nf)
            p.setPen(QColor(COLORS["muted"]))
            nr = QRectF(r.left() - 6, r.top() - 13, r.width() + 12, 12) if row == 0 else \
                QRectF(r.left() - 6, r.bottom() + 1, r.width() + 12, 12)
            p.drawText(nr, Qt.AlignmentFlag.AlignCenter, num)

    def _hit(self, pos):
        for r, name, _n, _row in self.rects:
            if r.adjusted(-2, -2, 2, 2).contains(QPointF(pos)):
                return name
        return None

    def mouseMoveEvent(self, e):
        name = self._hit(e.position())
        if name != self.hover:
            self.hover = name
            self.setCursor(Qt.CursorShape.PointingHandCursor if name else Qt.CursorShape.ArrowCursor)
            self.update()
        if name:
            QToolTip.showText(e.globalPosition().toPoint(), self.ports.get(name, {}).get("tip", name), self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, _e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        name = self._hit(e.position())
        if name:
            self.selected = name
            self.update()
            self.port_clicked.emit(name)


# ================================================================== light gauge
class LightGauge(QWidget):
    """Horizontal dBm scale with alarm/warning zones and a marker for the current reading."""
    LO, HI = -30.0, 5.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40)
        self.value = None
        self.warn = -12.0
        self.alarm = -15.0
        self.high = None

    def set_values(self, value, warn, alarm, high=None):
        self.value, self.warn, self.alarm, self.high = value, warn, alarm, high
        self.update()

    def _x(self, v, w):
        v = max(self.LO, min(self.HI, v))
        return 8 + (v - self.LO) / (self.HI - self.LO) * (w - 16)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        bar = QRectF(8, 8, w - 16, 10)
        zones = [(self.LO, self.alarm, "#F6D2CF"), (self.alarm, self.warn, "#FBEBB7"),
                 (self.warn, self.high if self.high is not None else self.HI, "#D5EFDC")]
        if self.high is not None:
            zones.append((self.high, self.HI, "#F6D2CF"))
        path = QPainterPath()
        path.addRoundedRect(bar, 5, 5)
        p.setClipPath(path)
        for a, b, col in zones:
            xa, xb = self._x(a, w), self._x(b, w)
            p.fillRect(QRectF(xa, bar.top(), xb - xa, bar.height()), QColor(col))
        p.setClipping(False)
        f = QFont(self.font())
        f.setPointSizeF(max(6.5, f.pointSizeF() - 2.5))
        p.setFont(f)
        p.setPen(QColor(COLORS["muted"]))
        for v in (self.alarm, self.warn):
            x = self._x(v, w)
            p.drawLine(QPointF(x, bar.top()), QPointF(x, bar.bottom()))
            p.drawText(QRectF(x - 24, bar.bottom() + 2, 48, 12), Qt.AlignmentFlag.AlignCenter, f"{v:g}")
        if self.value is None:
            return
        v = self.value
        col = COLORS["down"] if v < self.alarm or (self.high is not None and v > self.high) else \
            ("#B38600" if v < self.warn else COLORS["up"])
        x = self._x(v, w)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(col))
        p.drawPolygon(QPolygonF([QPointF(x - 6, 0), QPointF(x + 6, 0), QPointF(x, 9)]))
        p.drawRect(QRectF(x - 1.5, bar.top(), 3, bar.height()))


# =============================================================== Interface 360
def _section(text):
    lab = QLabel(text.upper())
    lab.setStyleSheet(f"color:{COLORS['muted']}; font-size:11px; font-weight:700; letter-spacing:0.6px;"
                      f"padding-top:8px;")
    return lab


class InterfacePanel(QFrame):
    close_requested = Signal()
    refresh_requested = Signal(str)
    run_command = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(340)
        self.name = None
        self.summary = {}
        self.ext = {}
        self.lldp = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        head = QFrame()
        head.setStyleSheet(f"QFrame{{border:none; border-bottom:1px solid {COLORS['border']};}}")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(16, 12, 10, 10)
        row = QHBoxLayout()
        cap = QLabel("INTERFACE 360")
        cap.setStyleSheet(f"color:{COLORS['muted']}; font-size:10px; font-weight:700; letter-spacing:1px;")
        row.addWidget(cap)
        row.addStretch(1)
        self.btn_refresh = QToolButton()
        self.btn_refresh.setObjectName("Icon")
        self.btn_refresh.setText("⟳")
        self.btn_refresh.setToolTip("Refresh this interface")
        self.btn_refresh.clicked.connect(lambda: self.name and self.refresh_requested.emit(self.name))
        close = QToolButton()
        close.setObjectName("Icon")
        close.setText("✕")
        close.setToolTip("Close")
        close.clicked.connect(lambda: self.close_requested.emit())
        row.addWidget(self.btn_refresh)
        row.addWidget(close)
        hl.addLayout(row)
        self.title = QLabel("–")
        self.title.setStyleSheet(f"font-size:20px; font-weight:600; color:{COLORS['interface']};")
        hl.addWidget(self.title)
        self.desc = QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setObjectName("Muted")
        hl.addWidget(self.desc)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        hl.addLayout(self.chips)
        outer.addWidget(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setStyleSheet("background:#FFFFFF;")
        self.bl = QVBoxLayout(body)
        self.bl.setContentsMargins(16, 4, 16, 16)
        self.bl.setSpacing(6)

        self.bl.addWidget(_section("Optical light"))
        self.gauge = LightGauge()
        self.bl.addWidget(self.gauge)
        self.optics_text = QLabel("–")
        self.optics_text.setWordWrap(True)
        self.optics_text.setTextFormat(Qt.TextFormat.RichText)
        self.bl.addWidget(self.optics_text)

        self.bl.addWidget(_section("Traffic & errors"))
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(4)
        self.bl.addLayout(self.grid)
        self.stats = {}
        for i, (key, label) in enumerate((("speed", "Speed"), ("mtu", "MTU"), ("in_rate", "Input rate"),
                                          ("out_rate", "Output rate"), ("in_errors", "Input errors"),
                                          ("crc", "CRC / Align"), ("framing", "Framing errors"),
                                          ("out_errors", "Output errors"), ("carrier", "Carrier transitions"),
                                          ("last_flapped", "Last flapped"))):
            k = QLabel(label)
            k.setObjectName("Muted")
            v = QLabel("–")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setWordWrap(True)
            v.setTextFormat(Qt.TextFormat.RichText)
            self.grid.addWidget(k, i, 0, Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(v, i, 1)
            self.stats[key] = v
        self.grid.setColumnStretch(1, 1)

        self.bl.addWidget(_section("LLDP neighbor"))
        self.lldp_text = QLabel("–")
        self.lldp_text.setWordWrap(True)
        self.lldp_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.bl.addWidget(self.lldp_text)

        self.bl.addWidget(_section("Recent log messages"))
        self.logs = OutputView(max_blocks=200)
        self.logs.setMinimumHeight(150)
        self.logs.setStyleSheet(f"border:1px solid {COLORS['border']}; border-radius:4px;")
        self.bl.addWidget(self.logs)

        self.bl.addWidget(_section("Actions"))
        acts = QGridLayout()
        acts.setSpacing(6)
        self.btn_ext = QPushButton("Extensive → CLI")
        self.btn_opt = QPushButton("Optics detail → CLI")
        self.btn_log = QPushButton("Log history → CLI")
        self.btn_note = QPushButton("Copy ticket note")
        self.btn_note.setObjectName("Primary")
        self.btn_ext.clicked.connect(lambda: self._run("show interfaces {n} extensive | no-more"))
        self.btn_opt.clicked.connect(lambda: self._run("show interfaces diagnostics optics {n} | no-more"))
        self.btn_log.clicked.connect(lambda: self._run("show log messages | match {n} | last 30 | no-more"))
        self.btn_note.clicked.connect(self.copy_ticket_note)
        acts.addWidget(self.btn_ext, 0, 0)
        acts.addWidget(self.btn_opt, 0, 1)
        acts.addWidget(self.btn_log, 1, 0)
        acts.addWidget(self.btn_note, 1, 1)
        self.bl.addLayout(acts)
        self.note_status = QLabel("")
        self.note_status.setObjectName("Muted")
        self.bl.addWidget(self.note_status)
        self.bl.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

    # ------------------------------------------------------------- content
    def _run(self, tpl):
        if self.name:
            self.run_command.emit(tpl.replace("{n}", self.name))

    def show_interface(self, name, summary: dict, device=""):
        """summary: description, admin, link, health, health_reason, rx, tx, rx_lanes, thr, flap, flap_age"""
        if name != self.name:
            self.ext, self.lldp = {}, {}
            for v in self.stats.values():
                v.setText("…")
            self.lldp_text.setText("Loading…")
            self.logs.setPlainText("Loading…")
            self.note_status.setText("")
        self.name, self.summary, self.device = name, summary, device
        self.title.setText(name)
        self.desc.setText(summary.get("description") or "No description")
        while self.chips.count():
            it = self.chips.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        admin = summary.get("admin")
        link = summary.get("link")
        if admin:
            self.chips.addWidget(chip("Admin " + admin.capitalize(), "up" if admin == "up" else "down"))
        if link:
            self.chips.addWidget(chip("Link " + link.capitalize(), "up" if link == "up" else "down"))
        health = summary.get("health")
        if health and health != "N/A":
            self.chips.addWidget(chip(health, {"OK": "up", "Warning": "warning"}.get(health, "down")))
        if summary.get("flap_age") is not None and summary.get("flap_recent"):
            self.chips.addWidget(chip("Flapped " + summary.get("flap_text", ""), "warning"))
        self.chips.addStretch(1)
        # optics
        thr = summary.get("thr", {})
        rx = summary.get("rx")
        warn = thr.get("rx_low_warn", summary.get("warn_default", -12.0))
        alarm = thr.get("rx_low_alarm", summary.get("alarm_default", -15.0))
        self.gauge.set_values(rx, warn, alarm, thr.get("rx_high_alarm"))
        if rx is None:
            self.optics_text.setText(f"<span style='color:{COLORS['muted']}'>No optic reading "
                                     "(copper / DAC / no transceiver)</span>")
        else:
            lanes = summary.get("rx_lanes") or []
            lane_txt = ("<br>Lanes Rx: " + ", ".join(f"{v:.2f}" for v in lanes)) if len(lanes) > 1 else ""
            tx = summary.get("tx")
            self.optics_text.setText(
                f"<b>Rx {rx:.2f} dBm</b> &nbsp; Tx {'–' if tx is None else f'{tx:.2f} dBm'}<br>"
                f"<span style='color:{COLORS['muted']}'>Warning {warn:g} · Alarm {alarm:g} dBm — "
                f"{summary.get('health_reason', '')}</span>{lane_txt}")
        if summary.get("last_flapped"):
            self.stats["last_flapped"].setText(summary["last_flapped"])

    def set_extensive(self, name, d: dict):
        if name != self.name:
            return
        self.ext = d

        def num(key, warn_if_nonzero=True):
            v = d.get(key)
            if v is None:
                return "–"
            if warn_if_nonzero and v:
                return f"<b style='color:{COLORS['down']}'>{v:,}</b>"
            return f"{v:,}"
        self.stats["speed"].setText(d.get("speed", "–"))
        self.stats["mtu"].setText(str(d.get("mtu", "–")))
        self.stats["in_rate"].setText(f"{fmt_bps(d.get('in_bps'))}  ({d.get('in_pps', 0):,} pps)"
                                      if "in_bps" in d else "–")
        self.stats["out_rate"].setText(f"{fmt_bps(d.get('out_bps'))}  ({d.get('out_pps', 0):,} pps)"
                                       if "out_bps" in d else "–")
        self.stats["in_errors"].setText(num("in_errors"))
        crc = (d.get("crc_rx"), d.get("crc_tx"))
        self.stats["crc"].setText("–" if crc[0] is None else
                                  f"{num('crc_rx')} rx / {num('crc_tx')} tx")
        self.stats["framing"].setText(num("in_framing errors"))
        self.stats["out_errors"].setText(num("out_errors"))
        self.stats["carrier"].setText(num("out_carrier transitions", warn_if_nonzero=False))
        if d.get("last_flapped"):
            self.stats["last_flapped"].setText(d["last_flapped"])
        for v in self.stats.values():
            if v.text() == "…":
                v.setText("–")

    def set_lldp(self, name, d: dict):
        if name != self.name:
            return
        self.lldp = d
        if not d:
            self.lldp_text.setText(f"<span style='color:{COLORS['muted']}'>No LLDP neighbor seen on this port</span>")
            return
        parts = [f"<b>{d.get('system', 'Unknown system')}</b>"]
        if d.get("port_id"):
            parts.append(f"Port {d['port_id']}" + (f" — {d['port_desc']}" if d.get("port_desc") else ""))
        if d.get("chassis"):
            parts.append(f"<span style='color:{COLORS['muted']}'>Chassis {d['chassis']}</span>")
        self.lldp_text.setText("<br>".join(parts))

    def set_logs(self, name, text):
        if name == self.name:
            self.logs.setPlainText(text.strip() or "No log messages mention this interface.")

    def ticket_note(self) -> str:
        s, d, l = self.summary, self.ext, self.lldp
        lines = [f"Device: {self.device}", f"Interface: {self.name}",
                 f"Description: {s.get('description') or '-'}",
                 f"Admin/Link: {(s.get('admin') or '-').capitalize()} / {(s.get('link') or '-').capitalize()}"]
        if s.get("last_flapped") or d.get("last_flapped"):
            lines.append(f"Last flapped: {d.get('last_flapped') or s.get('last_flapped')}")
        if s.get("rx") is not None:
            tx = s.get("tx")
            lines.append(f"Optics: Rx {s['rx']:.2f} dBm, Tx {'-' if tx is None else f'{tx:.2f}'} dBm "
                         f"({s.get('health', '-')}: {s.get('health_reason', '')})")
        if d:
            lines.append(f"Speed/MTU: {d.get('speed', '-')} / {d.get('mtu', '-')}")
            lines.append(f"Rates: in {fmt_bps(d.get('in_bps'))}, out {fmt_bps(d.get('out_bps'))}")
            lines.append(f"Errors: input {d.get('in_errors', '-')}, CRC {d.get('crc_rx', '-')}, "
                         f"framing {d.get('in_framing errors', '-')}, output {d.get('out_errors', '-')}, "
                         f"carrier transitions {d.get('out_carrier transitions', '-')}")
        if l:
            lines.append(f"LLDP neighbor: {l.get('system', '-')} port {l.get('port_id', '-')}")
        from datetime import datetime
        lines.append(f"Captured: {datetime.now():%Y-%m-%d %H:%M:%S}")
        return "\n".join(lines)

    def copy_ticket_note(self):
        if not self.name:
            return
        QApplication.clipboard().setText(self.ticket_note())
        self.note_status.setText("Ticket note copied to clipboard ✓")
