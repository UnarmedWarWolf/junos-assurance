"""Save CLI sessions and command output to Word (.docx) and Excel (.xlsx)."""
import re
from datetime import datetime

from .theme import EXPORT_HEX, tokenize, status_key

HEX = {k: v.lstrip("#") for k, v in EXPORT_HEX.items()}


def _meta_lines(meta: dict):
    meta = dict(meta or {})
    meta.setdefault("Saved", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return [(k, str(v)) for k, v in meta.items() if v not in (None, "")]


# ------------------------------------------------------------------ Word
def save_text_docx(text: str, path: str, title: str = "Junos CLI Session", meta: dict = None):
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn

    doc = Document()
    doc.add_heading(title, level=1)
    for k, v in _meta_lines(meta):
        p = doc.add_paragraph()
        r = p.add_run(f"{k}: ")
        r.bold = True
        p.add_run(v)

    for line in text.split("\n"):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing = 1.0
        for chunk, key in tokenize(line) or [("", None)]:
            run = p.add_run(chunk)
            run.font.name = "Consolas"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
            run.font.size = Pt(9)
            if key:
                run.font.color.rgb = RGBColor.from_string(HEX[key].upper())
                if key in ("down", "warning", "up"):
                    run.bold = True
    doc.save(path)
    return path


# ------------------------------------------------------------------ Excel
def _font_for(key, bold=False):
    from openpyxl.styles import Font
    if key:
        return Font(name="Consolas", size=10, color=HEX[key].upper(), bold=bold or key != "interface")
    return Font(name="Consolas", size=10, bold=bold)


def _write_header(ws, title, meta):
    from openpyxl.styles import Font
    ws["A1"] = title
    ws["A1"].font = Font(size=14, bold=True)
    row = 2
    for k, v in _meta_lines(meta):
        ws.cell(row=row, column=1, value=k).font = Font(bold=True, color="6B7785")
        ws.cell(row=row, column=2, value=v)
        row += 1
    return row + 1


def _rich_line(line):
    """Return a CellRichText with colored runs when openpyxl supports it, else plain text + key."""
    parts = tokenize(line)
    if len(parts) <= 1:
        return line, parts[0][1] if parts else None
    try:
        from openpyxl.cell.rich_text import CellRichText, TextBlock
        from openpyxl.cell.text import InlineFont
        from openpyxl.styles.colors import Color
        blocks = []
        for chunk, key in parts:
            if key:
                font = InlineFont(rFont="Consolas", sz=10, color=Color(rgb="FF" + HEX[key].upper()),
                                  b=key != "interface")
            else:
                font = InlineFont(rFont="Consolas", sz=10)
            blocks.append(TextBlock(font, chunk))
        return CellRichText(blocks), None
    except Exception:  # openpyxl < 3.1 has no rich text: color the whole cell instead
        return line, status_key(line)


def save_text_xlsx(text: str, path: str, title: str = "Junos CLI Session", meta: dict = None):
    """One CLI line per row, with color highlighting."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "CLI Session"
    row = _write_header(ws, title, meta)
    ws.cell(row=row - 1, column=1, value="Line")
    ws.cell(row=row - 1, column=2, value="Text")
    for i, line in enumerate(text.split("\n"), 1):
        ws.cell(row=row, column=1, value=i)
        value, key = _rich_line(line)
        c = ws.cell(row=row, column=2, value=value)
        if isinstance(value, str):
            c.font = _font_for(key)
        row += 1
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 140
    wb.save(path)
    return path


_KV_RE = re.compile(r"^\s*([^:]{2,60}?)\s+:\s+(.*)$")


def split_columns(line: str):
    """Heuristic: 'Key : value' -> [key, value]; otherwise split on 2+ spaces."""
    m = _KV_RE.match(line)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    parts = re.split(r"\s{2,}", line.strip())
    return parts if parts != [""] else []


def save_output_xlsx(command: str, output: str, path: str, meta: dict = None):
    """Command output -> Excel: a 'Table' sheet (split into columns) and a 'Raw' sheet."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    meta = dict(meta or {})
    meta["Command"] = command
    wb = Workbook()
    ws = wb.active
    ws.title = "Table"
    row = _write_header(ws, "Command Output", meta)
    widths = {}
    for line in output.split("\n"):
        cols = split_columns(line)
        if not cols:
            row += 1
            continue
        for ci, val in enumerate(cols, 1):
            c = ws.cell(row=row, column=ci, value=val)
            c.font = _font_for(status_key(val))
            widths[ci] = max(widths.get(ci, 8), min(len(val) + 2, 80))
        row += 1
    from openpyxl.utils import get_column_letter
    for ci, w in widths.items():
        ws.column_dimensions[get_column_letter(ci)].width = w

    raw = wb.create_sheet("Raw")
    raw["A1"] = command
    raw["A1"].font = Font(bold=True)
    raw["A1"].fill = PatternFill("solid", fgColor="E6F5FB")
    for i, line in enumerate(output.split("\n"), 2):
        value, key = _rich_line(line)
        c = raw.cell(row=i, column=1, value=value)
        if isinstance(value, str):
            c.font = _font_for(key)
    raw.column_dimensions["A"].width = 140
    wb.save(path)
    return path


def save_tables_xlsx(tables: dict, path: str, meta: dict = None):
    """tables = {'Sheet name': (headers, rows)} -> one sheet each (used by dashboard export)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    first = True
    for name, (headers, rows) in tables.items():
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = name[:31]
        r = _write_header(ws, name, meta)
        for ci, h in enumerate(headers, 1):
            c = ws.cell(row=r, column=ci, value=h)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="049FD9")
        widths = {ci: len(h) + 4 for ci, h in enumerate(headers, 1)}
        for row in rows:
            r += 1
            for ci, val in enumerate(row, 1):
                c = ws.cell(row=r, column=ci, value=val)
                key = status_key(str(val)) if val is not None else None
                if key:
                    c.font = Font(color=HEX[key].upper(), bold=key != "interface")
                widths[ci] = max(widths.get(ci, 8), min(len(str(val)) + 2, 70))
        for ci, w in widths.items():
            ws.column_dimensions[get_column_letter(ci)].width = w
        ws.freeze_panes = ws.cell(row=r - len(rows) + 1, column=1) if rows else None
    wb.save(path)
    return path
