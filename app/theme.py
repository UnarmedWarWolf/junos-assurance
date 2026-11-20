"""Colors, light/dark themes, stylesheet and the shared text-coloring rules.

`color_spans()` drives the live CLI highlighter, the dashboard tables and the
Word / Excel exporters, so colors are identical everywhere.

COLORS / STATUS_HEX are mutated in place by `set_dark()`, so code that reads
them at paint/refresh time follows the active theme automatically.
"""
import re

LIGHT = {
    "page": "#F4F6F9", "panel": "#FFFFFF", "border": "#DCE2E9", "text": "#1F2D3D", "muted": "#6B7785",
    "accent": "#049FD9", "accent_dark": "#0277A8", "header": "#FFFFFF",
    "down": "#D0271D", "warning": "#C99700", "up": "#2E9E44", "interface": "#7B3FBF",
    "console_bg": "#FFFFFF", "alt_row": "#FAFBFC", "selection": "#E6F5FB", "hover": "#F0F7FB",
    "up_bg": "#E7F6EC", "down_bg": "#FCE9E8", "warning_bg": "#FFF6DB", "interface_bg": "#F1EAFB",
    "neutral_bg": "#EEF1F4", "warning_text": "#9A7400",
    "gauge_red": "#F6D2CF", "gauge_amber": "#FBEBB7", "gauge_green": "#D5EFDC",
    "port_disabled": "#C5CDD6", "port_outline": "#7D8B99", "nav_bg": "#FFFFFF", "nav_active": "#E6F5FB",
    "find_hit": "#FFE58A", "find_current": "#FFB347",
}
DARK = {
    "page": "#14181D", "panel": "#1D232A", "border": "#2E3741", "text": "#E4E9EE", "muted": "#94A0AC",
    "accent": "#2BB0E6", "accent_dark": "#1C8FBF", "header": "#1D232A",
    "down": "#FF6B61", "warning": "#F2C230", "up": "#4CC46A", "interface": "#B892FF",
    "console_bg": "#171C21", "alt_row": "#20272E", "selection": "#123A4C", "hover": "#24303A",
    "up_bg": "#163A22", "down_bg": "#4A1F1C", "warning_bg": "#46390F", "interface_bg": "#33265A",
    "neutral_bg": "#2A323B", "warning_text": "#F2C230",
    "gauge_red": "#5A2622", "gauge_amber": "#5A4A16", "gauge_green": "#1F4A2C",
    "port_disabled": "#4A5561", "port_outline": "#0E1115", "nav_bg": "#1D232A", "nav_active": "#123A4C",
    "find_hit": "#6B5A12", "find_current": "#A8641A",
}

COLORS = dict(LIGHT)
STATUS_HEX = {}
_DARK = False


def _sync_status():
    STATUS_HEX.clear()
    STATUS_HEX.update({k: COLORS[k] for k in ("down", "warning", "up", "interface")})


_sync_status()


def set_dark(dark: bool):
    global _DARK
    _DARK = bool(dark)
    COLORS.clear()
    COLORS.update(DARK if dark else LIGHT)
    _sync_status()


def is_dark() -> bool:
    return _DARK


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
             r"inactive|no light|error|denied|refused|timeout|timed out|poor)" + _E,
        re.IGNORECASE)),
    ("warning", re.compile(_B + r"(?:warning|warnings|warn|minor|degraded|fair)" + _E, re.IGNORECASE)),
    ("up", re.compile(_B + r"(?:up|enabled|ok|online|present|good|healthy)" + _E, re.IGNORECASE)),
]


def color_spans(line: str):
    """Return non-overlapping (start, end, key) spans for one line of text."""
    spans, taken = [], []

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
    """Pick a single color key for a table cell (first match wins)."""
    if not text:
        return None
    if INTERFACE_RE.fullmatch(text.strip()):
        return "interface"
    for key, rx in STATUS_PATTERNS:
        if rx.search(text):
            return key
    return None


# Exporters always use the light (print-friendly) colors
EXPORT_HEX = {k: LIGHT[k] for k in ("down", "warning", "up", "interface")}


def build_stylesheet() -> str:
    c = COLORS
    return f"""
QMainWindow, QWidget#Page, QWidget#Stack {{ background: {c['page']}; }}
QWidget {{ color: {c['text']}; }}
QWidget#PanelBody, QScrollArea#PanelScroll > QWidget > QWidget {{ background: {c['panel']}; }}
QFrame#Header {{ background: {c['header']}; border-bottom: 1px solid {c['border']}; }}
QLabel#Brand {{ font-size: 18px; font-weight: 600; }}
QLabel#BrandMark {{ font-size: 20px; color: {c['accent']}; }}
QLabel#Crumb {{ color: {c['muted']}; }}
QFrame#Card {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px; }}
QFrame#Rule {{ border: none; border-bottom: 1px solid {c['border']}; }}
QFrame#Boxed {{ border: 1px solid {c['border']}; border-radius: 4px; background: {c['console_bg']}; }}
QLabel#CardTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#FieldLabel {{ color: {c['muted']}; font-size: 12px; }}
QLabel#Muted {{ color: {c['muted']}; font-size: 12px; }}
QLabel#Section {{ color: {c['muted']}; font-size: 11px; font-weight: 700; letter-spacing: 0.6px; padding-top: 8px; }}
QLabel#KpiValue {{ font-size: 28px; font-weight: 300; }}
QLabel#KpiTitle {{ color: {c['muted']}; font-size: 12px; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#Badge {{ background: {c['page']}; border: 1px solid {c['border']}; border-radius: 9px;
                padding: 1px 8px; color: {c['muted']}; font-size: 11px; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
    background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 5px 7px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {c['accent']}; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; selection-background-color: {c['selection']}; }}
QPushButton {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}
QPushButton:disabled {{ color: {c['muted']}; }}
QPushButton#Primary {{ background: {c['accent']}; color: #FFFFFF; border: 1px solid {c['accent']}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {c['accent_dark']}; color: #FFFFFF; }}
QPushButton#Danger {{ color: {c['down']}; }}
QPushButton#Link {{ border: none; background: transparent; color: {c['accent']}; padding: 2px 4px; text-align: left; }}
QToolButton {{ color: {c['text']}; }}
QToolButton#Dropdown {{ background: {c['accent']}; color: #FFFFFF; border: none; border-radius: 4px;
                        padding: 8px 12px; font-weight: 600; text-align: left; }}
QToolButton#Dropdown:hover {{ background: {c['accent_dark']}; }}
QToolButton#Icon {{ border: none; padding: 4px; color: {c['muted']}; font-size: 16px; }}
QToolButton#Icon:hover {{ color: {c['accent']}; }}
QToolButton#Flat {{ border: 1px solid {c['border']}; border-radius: 4px; padding: 4px 9px; background: {c['panel']}; }}
QToolButton#Flat:hover {{ border-color: {c['accent']}; }}
QFrame#NavRail {{ background: {c['nav_bg']}; border-right: 1px solid {c['border']}; }}
QToolButton#Nav {{ border: none; border-radius: 6px; padding: 6px 2px; color: {c['muted']};
                   font-size: 11px; min-width: 62px; }}
QToolButton#Nav:hover {{ background: {c['hover']}; color: {c['text']}; }}
QToolButton#Nav:checked {{ background: {c['nav_active']}; color: {c['accent']}; font-weight: 600; }}
QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 14px; }}
QMenu::item:selected {{ background: {c['selection']}; color: {c['accent']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}
QTableWidget, QListWidget, QTreeWidget {{ background: {c['panel']}; border: none; gridline-color: {c['border']};
                alternate-background-color: {c['alt_row']};
                selection-background-color: {c['selection']}; selection-color: {c['text']}; }}
QListWidget::item {{ padding: 6px 4px; border-bottom: 1px solid {c['border']}; }}
QHeaderView::section {{ background: {c['panel']}; border: none; border-bottom: 2px solid {c['border']};
                        padding: 6px; font-weight: 600; color: {c['muted']}; font-size: 12px; }}
QPlainTextEdit#Console, QTextBrowser {{ background: {c['console_bg']}; border: none; color: {c['text']}; }}
QLineEdit#CliInput {{ border: none; border-top: 1px solid {c['border']}; border-radius: 0; padding: 8px;
                      background: {c['console_bg']}; }}
QFrame#FindBar {{ background: {c['page']}; border-top: 1px solid {c['border']}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: {c['page']}; border: 1px solid {c['border']}; border-bottom: none;
                padding: 7px 14px; margin-right: 3px; border-top-left-radius: 6px; border-top-right-radius: 6px;
                color: {c['muted']}; }}
QTabBar::tab:selected {{ background: {c['panel']}; color: {c['text']}; font-weight: 600;
                         border-top: 2px solid {c['accent']}; }}
QSplitter::handle {{ background: {c['page']}; }}
QScrollArea {{ background: transparent; }}
QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 6px; }}
QStatusBar {{ background: {c['header']}; border-top: 1px solid {c['border']}; color: {c['muted']}; }}
QCheckBox {{ spacing: 6px; }}
QDialog {{ background: {c['panel']}; }}
"""


def apply_theme(app, dark: bool):
    """Switch the whole application between light and dark."""
    from PySide6.QtGui import QColor, QPalette
    set_dark(dark)
    c = COLORS
    pal = QPalette()
    for role, col in ((QPalette.ColorRole.Window, c["page"]), (QPalette.ColorRole.Base, c["panel"]),
                      (QPalette.ColorRole.AlternateBase, c["alt_row"]), (QPalette.ColorRole.Text, c["text"]),
                      (QPalette.ColorRole.WindowText, c["text"]), (QPalette.ColorRole.Button, c["panel"]),
                      (QPalette.ColorRole.ButtonText, c["text"]), (QPalette.ColorRole.Highlight, c["accent"]),
                      (QPalette.ColorRole.HighlightedText, "#FFFFFF"), (QPalette.ColorRole.ToolTipBase, c["panel"]),
                      (QPalette.ColorRole.ToolTipText, c["text"]), (QPalette.ColorRole.PlaceholderText, c["muted"])):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(build_stylesheet())


# Back-compat for code that imported STYLESHEET
STYLESHEET = build_stylesheet()
