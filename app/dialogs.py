"""Larger dialogs: Explain output, Playbook runner, Snapshots / diff, Device editor."""
import html
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QTextBrowser, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from .explainer import explain
from .playbooks import FAIL, INFO, OK, WARN, PlaybookRun
from .theme import COLORS, STATUS_HEX, tokenize
from .widgets import chip, mono_font

STATUS_ICON = {OK: ("✓", "up"), WARN: ("!", "warning"), FAIL: ("✕", "down"), INFO: ("i", None)}


def _hex(key):
    return STATUS_HEX.get(key, COLORS["muted"])


def _colored_line_html(line):
    out = []
    for text, key in tokenize(line):
        t = html.escape(text)
        out.append(f"<span style='color:{_hex(key)};font-weight:{700 if key and key != 'interface' else 400}'>{t}</span>"
                   if key else t)
    return "".join(out)


# ================================================================ Explain
class ExplainDialog(QDialog):
    def __init__(self, text, title="Explain output", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 640)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        res = explain(text)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        t = QLabel(title)
        t.setObjectName("CardTitle")
        lay.addWidget(t)
        chips = QHBoxLayout()
        for txt, key in res["summary"]:
            chips.addWidget(chip(txt, key))
        chips.addStretch(1)
        lay.addLayout(chips)
        b = QTextBrowser()
        b.setOpenExternalLinks(False)
        mono = mono_font(10).family()
        rows = []
        for no, line, meaning, key in res["notes"]:
            dot = f"<span style='color:{_hex(key)}'>●</span>" if key else f"<span style='color:{COLORS['muted']}'>○</span>"
            rows.append(f"<tr><td style='color:{COLORS['muted']};padding:6px 8px;vertical-align:top'>{no}</td>"
                        f"<td style='font-family:\"{mono}\";padding:6px 10px;vertical-align:top;"
                        f"white-space:pre'>{_colored_line_html(line.strip())}</td>"
                        f"<td style='padding:6px 8px;vertical-align:top'>{dot}</td>"
                        f"<td style='padding:6px 8px;vertical-align:top'>{html.escape(meaning)}</td></tr>")
        b.setHtml(f"<table cellspacing='0' width='100%'>"
                  f"<tr><th align='left' style='color:{COLORS['muted']};padding:6px 8px'>Line</th>"
                  f"<th align='left' style='color:{COLORS['muted']};padding:6px 10px'>Output</th><th></th>"
                  f"<th align='left' style='color:{COLORS['muted']};padding:6px 8px'>What it means</th></tr>"
                  + "".join(rows) + "</table>")
        lay.addWidget(b, 1)
        self.plain = "\n".join(f"{line.strip()}\n    → {meaning}" for _n, line, meaning, _k in res["notes"])
        row = QHBoxLayout()
        row.addStretch(1)
        cp = QPushButton("Copy explanation")
        cp.clicked.connect(lambda: QApplication.clipboard().setText(self.plain))
        close = QPushButton("Close")
        close.setObjectName("Primary")
        close.clicked.connect(self.close)
        row.addWidget(cp)
        row.addWidget(close)
        lay.addLayout(row)


# =============================================================== Playbook
class PlaybookDialog(QDialog):
    """Runs a playbook step by step through the device tab's command queue."""

    def __init__(self, playbook, iface, enqueue, device="", warn_default=-12.0, alarm_default=-15.0, parent=None):
        super().__init__(parent)
        self.playbook, self.iface, self.enqueue, self.device = playbook, iface, enqueue, device
        self.defaults = (warn_default, alarm_default)
        self.closed = False
        self.setWindowTitle(f"{playbook.name} – {iface}")
        self.resize(820, 640)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        head = QHBoxLayout()
        t = QLabel(playbook.name)
        t.setObjectName("CardTitle")
        head.addWidget(t)
        ic = QLabel(iface)
        ic.setStyleSheet(f"color:{COLORS['interface']}; font-weight:600; font-size:14px;")
        head.addWidget(ic)
        head.addStretch(1)
        self.progress = QLabel("")
        self.progress.setObjectName("Muted")
        head.addWidget(self.progress)
        lay.addLayout(head)
        d = QLabel(playbook.description + " Click a step to see the command and its raw output.")
        d.setWordWrap(True)
        d.setObjectName("Muted")
        lay.addWidget(d)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Step", "Finding"])
        self.tree.setRootIsDecorated(True)
        self.tree.setWordWrap(True)
        self.tree.setUniformRowHeights(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setStretchLastSection(True)
        lay.addWidget(self.tree, 1)

        self.verdict = QFrame()
        self.verdict.setObjectName("Card")
        vl = QVBoxLayout(self.verdict)
        vl.setContentsMargins(14, 10, 14, 10)
        self.v_head = QLabel("Running…")
        self.v_head.setStyleSheet("font-size:15px; font-weight:600;")
        self.v_head.setWordWrap(True)
        self.v_body = QLabel("")
        self.v_body.setWordWrap(True)
        self.v_body.setTextFormat(Qt.TextFormat.RichText)
        self.v_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        vl.addWidget(QLabel("VERDICT"))
        vl.itemAt(0).widget().setObjectName("Section")
        vl.addWidget(self.v_head)
        vl.addWidget(self.v_body)
        lay.addWidget(self.verdict)

        row = QHBoxLayout()
        self.b_again = QPushButton("Run again")
        self.b_again.clicked.connect(self.start)
        self.b_copy = QPushButton("Copy report")
        self.b_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.report()))
        close = QPushButton("Close")
        close.setObjectName("Primary")
        close.clicked.connect(self.close)
        row.addWidget(self.b_again)
        row.addWidget(self.b_copy)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.start()

    def closeEvent(self, e):
        self.closed = True
        super().closeEvent(e)

    def start(self):
        self.run = PlaybookRun(self.playbook, self.iface, *self.defaults)
        self.tree.clear()
        self.items = []
        for st in self.playbook.steps:
            it = QTreeWidgetItem(["…", st.title, "Waiting"])
            it.setForeground(2, QColor(COLORS["muted"]))
            self.tree.addTopLevelItem(it)
            self.items.append(it)
        self.v_head.setText("Running…")
        self.v_head.setStyleSheet("font-size:15px; font-weight:600;")
        self.v_body.setText("")
        self.b_again.setEnabled(False)
        self._next()

    def _next(self):
        if self.closed:
            return
        cmd = self.run.next_command()
        if cmd is None:
            self._finish()
            return
        i = len(self.run.results)
        self.items[i].setText(0, "⏳")
        self.items[i].setText(2, "Running…")
        self.progress.setText(f"Step {i + 1} of {len(self.playbook.steps)}")
        job = self.enqueue(cmd, background=True, tag="playbook", callback=self._got)
        if job is None:
            self.items[i].setText(2, "Not connected")
            self.v_head.setText("Not connected – connect to the switch and run again.")
            self.b_again.setEnabled(True)

    def _got(self, job):
        if self.closed:
            return
        r = self.run.feed(job.output)
        it = self.items[len(self.run.results) - 1]
        icon, key = STATUS_ICON.get(r.status, ("i", None))
        it.setText(0, icon)
        it.setForeground(0, QColor(_hex(key)))
        it.setText(2, r.finding)
        it.setForeground(2, QColor(COLORS["text"]))
        it.setToolTip(2, r.finding)
        child = QTreeWidgetItem([f"› {r.command}"])
        child.setFont(0, mono_font(9))
        child.setForeground(0, QColor(COLORS["muted"]))
        it.addChild(child)
        child.setFirstColumnSpanned(True)
        out = QTreeWidgetItem([""])
        it.addChild(out)
        out.setFirstColumnSpanned(True)
        view = QPlainTextEdit(r.output.strip() or "(no output)")
        view.setReadOnly(True)
        view.setFont(mono_font(9))
        view.setFixedHeight(min(260, 26 + 16 * max(2, len(r.output.splitlines()))))
        self.tree.setItemWidget(out, 0, view)
        self._next()

    def _finish(self):
        status, headline, advice = self.run.verdict()
        icon, key = STATUS_ICON.get(status, ("i", None))
        self.v_head.setText(f"{icon}  {headline}")
        self.v_head.setStyleSheet(f"font-size:15px; font-weight:600; color:{_hex(key)};")
        self.v_body.setText("<ul style='margin-left:-20px'>" + "".join(f"<li>{html.escape(a)}</li>" for a in advice)
                            + "</ul>")
        self.progress.setText("Done")
        self.b_again.setEnabled(True)

    def report(self):
        lines = [f"{self.playbook.name}", f"Device: {self.device}   Interface: {self.iface}",
                 f"Run: {datetime.now():%Y-%m-%d %H:%M:%S}", ""]
        for r in self.run.results:
            lines.append(f"[{r.status.upper():4}] {r.title}: {r.finding}")
        if self.run.done:
            status, headline, advice = self.run.verdict()
            lines += ["", f"VERDICT: {headline}"] + [f"  - {a}" for a in advice]
        return "\n".join(lines)


# ============================================================== Snapshots
class SnapshotDiffDialog(QDialog):
    def __init__(self, rows, before_label, after_label, export_fn=None, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.setWindowTitle("Snapshot comparison")
        self.resize(900, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        t = QLabel("What changed")
        t.setObjectName("CardTitle")
        lay.addWidget(t)
        sub = QLabel(f"Before: {before_label}     →     After: {after_label}")
        sub.setObjectName("Muted")
        lay.addWidget(sub)
        counts = {}
        for r in rows:
            counts[r[4]] = counts.get(r[4], 0) + 1
        chips = QHBoxLayout()
        if not rows:
            chips.addWidget(chip("No changes", "up"))
        if counts.get("down"):
            chips.addWidget(chip(f"{counts['down']} problems", "down"))
        if counts.get("warning"):
            chips.addWidget(chip(f"{counts['warning']} warnings", "warning"))
        if counts.get("up"):
            chips.addWidget(chip(f"{counts['up']} improvements", "up"))
        chips.addStretch(1)
        lay.addLayout(chips)
        tbl = QTableWidget(len(rows), 4)
        tbl.setHorizontalHeaderLabels(["Interface", "Change", "Before", "After"])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setAlternatingRowColors(True)
        tbl.setShowGrid(False)
        for i, (iface, change, before, after, key) in enumerate(rows):
            vals = [iface, change, before, after]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c == 0:
                    it.setForeground(QColor(STATUS_HEX["interface"]))
                elif c == 1 and key:
                    it.setForeground(QColor(_hex(key)))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                tbl.setItem(i, c, it)
        tbl.resizeColumnsToContents()
        tbl.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(tbl, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        if export_fn:
            ex = QPushButton("Export to Excel…")
            ex.clicked.connect(lambda: export_fn(rows, before_label, after_label))
            row.addWidget(ex)
        close = QPushButton("Close")
        close.setObjectName("Primary")
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)


class SnapshotsDialog(QDialog):
    """List / take / compare / delete snapshots for one device."""

    def __init__(self, history, device, take_fn, compare_now_fn, compare_fn, parent=None):
        super().__init__(parent)
        self.history, self.device = history, device
        self.take_fn, self.compare_now_fn, self.compare_fn = take_fn, compare_now_fn, compare_fn
        self.setWindowTitle(f"Snapshots – {device}")
        self.resize(560, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        t = QLabel("Before / after snapshots")
        t.setObjectName("CardTitle")
        lay.addWidget(t)
        d = QLabel("Take a snapshot before maintenance, then compare it with the switch now (or with another "
                   "snapshot) to see which ports went down, flapped or lost light.")
        d.setWordWrap(True)
        d.setObjectName("Muted")
        lay.addWidget(d)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        b_take = QPushButton("Take snapshot now")
        b_take.setObjectName("Primary")
        b_take.clicked.connect(self._take)
        b_now = QPushButton("Compare with now")
        b_now.clicked.connect(self._compare_now)
        b_two = QPushButton("Compare selected two")
        b_two.clicked.connect(self._compare_two)
        b_del = QPushButton("Delete")
        b_del.setObjectName("Danger")
        b_del.clicked.connect(self._delete)
        for b in (b_take, b_now, b_two, b_del):
            row.addWidget(b)
        lay.addLayout(row)
        self.reload()

    def reload(self):
        self.list.clear()
        for sid, ts, _dev, label in self.history.list_snapshots(self.device):
            it = QListWidgetItem(f"{datetime.fromtimestamp(ts):%Y-%m-%d %H:%M:%S}    {label}")
            it.setData(Qt.ItemDataRole.UserRole, sid)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _selected(self):
        return [it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems()]

    def _take(self):
        label, ok = QInputDialog.getText(self, "Take snapshot", "Label (e.g. 'Before CHG123456'):",
                                         text=f"Before change {datetime.now():%H:%M}")
        if ok:
            self.take_fn(label or "Snapshot", self.reload)

    def _compare_now(self):
        sel = self._selected()
        if len(sel) != 1:
            QMessageBox.information(self, "Snapshots", "Select one snapshot to compare with the switch now.")
            return
        self.compare_now_fn(sel[0])

    def _compare_two(self):
        sel = self._selected()
        if len(sel) != 2:
            QMessageBox.information(self, "Snapshots", "Select exactly two snapshots (Ctrl+click).")
            return
        self.compare_fn(*sorted(sel))

    def _delete(self):
        sel = self._selected()
        if sel and QMessageBox.question(self, "Snapshots", f"Delete {len(sel)} snapshot(s)?") == \
                QMessageBox.StandardButton.Yes:
            for sid in sel:
                self.history.delete_snapshot(sid)
            self.reload()


# ========================================================== Device editor
class DeviceEditDialog(QDialog):
    def __init__(self, dev=None, parent=None):
        super().__init__(parent)
        from .inventory import Device
        self.dev = dev or Device(hostname="")
        self.setWindowTitle("Edit device" if dev else "Add device")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.f = {}
        for key, label, ph in (("hostname", "Hostname", "qfx-core-01"), ("site", "Site", "Columbus"),
                               ("role", "Role", "Core / Access / Aggregation"), ("tags", "Tags", "metro, ring-3"),
                               ("notes", "Notes", "")):
            e = QLineEdit(getattr(self.dev, key))
            e.setPlaceholderText(ph)
            self.f[key] = e
            form.addRow(label, e)
        self.fav = QCheckBox("Favorite (pinned to the top)")
        self.fav.setChecked(self.dev.favorite)
        form.addRow("", self.fav)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        if not self.f["hostname"].text().strip():
            self.f["hostname"].setFocus()
            return
        self.accept()

    def result_device(self):
        from .inventory import Device
        d = Device(**{k: e.text().strip() for k, e in self.f.items()})
        d.favorite = self.fav.isChecked()
        d.last_connected = self.dev.last_connected
        d.health = self.dev.health
        return d


def save_path(parent, title, default, filt, start_dir):
    import os
    path, _ = QFileDialog.getSaveFileName(parent, title, os.path.join(start_dir, default), filt)
    return path
