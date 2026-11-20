"""Colours, stylesheet and the shared text-colouring rules.

The same `color_spans()` function drives the live CLI highlighter, the
dashboard tables and the Word / Excel exporters, so colours are identical
everywhere.
"""
import re

COLORS = {
    "page": "#F4F6F9",
    "panel": "#FFFFFF",
    "border": "#DCE2E9",
    "text": "#1F2D3D",
    "muted": "#6B7785",
    "accent": "#049FD9",        # Cisco-style blue
    "accent_dark": "#0277A8",
    "header": "#FFFFFF",
    "down": "#D0271D",          # red   - down / errors
    "warning": "#C99700",       # amber - warnings (readable "yellow" on white)
    "up": "#2E9E44",            # green - up / enabled
    "interface": "#7B3FBF",     # purple - interface names
    "console_bg": "#FFFFFF",
}

STATUS_HEX = {
    "down": COLORS["down"],
    "warning": COLORS["warning"],
    "up": COLORS["up"],
    "interface": COLORS["interface"],
}

# Interface names: xe-0/0/0, ge-1/0/12.0, et-0/0/48:1, ae0, lo0.0, irb.100 ...
INTERFACE_RE = re.compile(
    r"(?<![\w-])(?:"
    r"(?:xe|ge|et|fe|mge|gr|lt|ip|st|vt|pe|pfe|pfh|sp|ms|cbp|so|t1|e1)-\d+/\d+/\d+(?::\d+)?"
    r"|(?:ae|lo|em|fxp|me|vme|reth|fab|bme|jsrv)\d+"
    r"|(?:irb|vlan)\.\d+"
    r")(?:\.\d+)?(?![\w/])",
    re.IGNORECASE,
)

_B = r"(?<![\w\-./])"   # word boundary that treats - . / as part of a word
_E = r"(?![\w\-./])"

STATUS_PATTERNS = [
    ("down", re.compile(
        _B + r"(?:down|disabled|failed|failure|fail|critical|absent|offline|unreachable|"
             r"inactive|no light|error|denied|refused|timeout|timed out)" + _E,
        re.IGNORECASE)),
    ("warning", re.compile(_B + r"(?:warning|warnings|warn|minor|degraded)" + _E, re.IGNORECASE)),
    ("up", re.compile(_B + r"(?:up|enabled|ok|online|present|good|healthy)" + _E, re.IGNORECASE)),
]


def color_spans(line: str):
    """Return non-overlapping (start, end, key) spans for one line of text."""
    spans = []
    taken = []

    def free(s, e):
        return all(e <= ts or s >= te for ts, te in taken)

    for m in INTERFACE_RE.finditer(line):
        spans.append((m.start(), m.end(), "interface"))
        taken.append((m.start(), m.end()))
    for key, rx in STATUS_PATTERNS:
        for m in rx.finditer(line):
            if free(m.start(), m.end()):
                spans.append((m.start(), m.end(), key))
                taken.append((m.start(), m.end()))
    spans.sort()
    return spans


def tokenize(line: str):
    """Split a line into [(text, key_or_None), ...] using color_spans."""
    out, pos = [], 0
    for s, e, key in color_spans(line):
        if s > pos:
            out.append((line[pos:s], None))
        out.append((line[s:e], key))
        pos = e
    if pos < len(line):
        out.append((line[pos:], None))
    return out


def status_key(text: str):
    """Pick a single colour key for a table cell (first match wins)."""
    if not text:
        return None
    if INTERFACE_RE.fullmatch(text.strip()):
        return "interface"
    for key, rx in STATUS_PATTERNS:
        if rx.search(text):
            return key
    return None


STYLESHEET = f"""
QMainWindow, QWidget#Page {{ background: {COLORS['page']}; }}
QWidget {{ color: {COLORS['text']}; }}
QFrame#Header {{ background: {COLORS['header']}; border-bottom: 1px solid {COLORS['border']}; }}
QLabel#Brand {{ font-size: 18px; font-weight: 600; color: {COLORS['text']}; }}
QLabel#BrandMark {{ font-size: 20px; color: {COLORS['accent']}; }}
QLabel#Crumb {{ color: {COLORS['muted']}; font-size: 13px; }}
QFrame#Card {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']}; border-radius: 6px; }}
QLabel#CardTitle {{ font-size: 14px; font-weight: 600; color: {COLORS['text']}; }}
QLabel#FieldLabel {{ color: {COLORS['muted']}; font-size: 12px; }}
QLabel#Muted {{ color: {COLORS['muted']}; font-size: 12px; }}
QLabel#KpiValue {{ font-size: 28px; font-weight: 300; }}
QLabel#KpiTitle {{ color: {COLORS['muted']}; font-size: 12px; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#Badge {{ background: {COLORS['page']}; border: 1px solid {COLORS['border']}; border-radius: 9px;
                padding: 1px 8px; color: {COLORS['muted']}; font-size: 11px; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #FFFFFF; border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 5px 7px; min-height: 18px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {COLORS['accent']}; }}
QPushButton {{ background: #FFFFFF; border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {COLORS['accent']}; color: {COLORS['accent_dark']}; }}
QPushButton:disabled {{ color: #A9B3BE; }}
QPushButton#Primary {{ background: {COLORS['accent']}; color: #FFFFFF; border: 1px solid {COLORS['accent']}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {COLORS['accent_dark']}; color: #FFFFFF; }}
QPushButton#Primary:disabled {{ background: #9FD3EA; border-color: #9FD3EA; }}
QPushButton#Danger {{ color: {COLORS['down']}; }}
QToolButton#Dropdown {{ background: {COLORS['accent']}; color: #FFFFFF; border: none; border-radius: 4px;
                        padding: 8px 12px; font-weight: 600; text-align: left; }}
QToolButton#Dropdown:hover {{ background: {COLORS['accent_dark']}; }}
QToolButton#Dropdown::menu-indicator {{ subcontrol-position: right center; right: 8px; }}
QToolButton#Icon {{ border: none; padding: 4px; color: {COLORS['muted']}; font-size: 16px; }}
QToolButton#Icon:hover {{ color: {COLORS['accent']}; }}
QMenu {{ background: #FFFFFF; border: 1px solid {COLORS['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 14px; }}
QMenu::item:selected {{ background: #E6F5FB; color: {COLORS['accent_dark']}; }}
QMenu::separator {{ height: 1px; background: {COLORS['border']}; margin: 4px 6px; }}
QTableWidget {{ background: #FFFFFF; border: none; gridline-color: #EEF1F4; alternate-background-color: #FAFBFC;
                selection-background-color: #E6F5FB; selection-color: {COLORS['text']}; }}
QHeaderView::section {{ background: #FFFFFF; border: none; border-bottom: 2px solid {COLORS['border']};
                        padding: 6px; font-weight: 600; color: {COLORS['muted']}; font-size: 12px; }}
QPlainTextEdit#Console {{ background: {COLORS['console_bg']}; border: none; }}
QLineEdit#CliInput {{ border: none; border-top: 1px solid {COLORS['border']}; border-radius: 0; padding: 8px; }}
QSplitter::handle {{ background: {COLORS['page']}; }}
QToolTip {{ background: #FFFFFF; color: {COLORS['text']}; border: 1px solid {COLORS['border']}; padding: 6px; }}
QCheckBox {{ spacing: 6px; }}
QStatusBar {{ background: #FFFFFF; border-top: 1px solid {COLORS['border']}; color: {COLORS['muted']}; }}
"""
