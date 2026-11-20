"""Local history: optical light samples (for trends/sparklines) and before/after snapshots.

Stored in SQLite at <settings folder>/history.db. Pure Python, no Qt.
"""
import json
import sqlite3
import threading
import time
from pathlib import Path

from .parsers import split_port


class History:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock, self.conn:
            self.conn.execute("CREATE TABLE IF NOT EXISTS optics (ts REAL, device TEXT, iface TEXT, rx REAL, tx REAL)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS ix_optics ON optics (device, iface, ts)")
            self.conn.execute("CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                              "ts REAL, device TEXT, label TEXT, data TEXT)")

    # ------------------------------------------------------------ optics
    def record_optics(self, device: str, samples: dict, ts: float = None):
        """samples = {iface: (rx_dbm_or_None, tx_dbm_or_None)}"""
        ts = ts or time.time()
        rows = [(ts, device, i, rx, tx) for i, (rx, tx) in samples.items() if rx is not None or tx is not None]
        if not rows:
            return
        with self._lock, self.conn:
            self.conn.executemany("INSERT INTO optics VALUES (?,?,?,?,?)", rows)

    def series(self, device: str, iface: str, hours: float = 72):
        since = time.time() - hours * 3600
        with self._lock:
            cur = self.conn.execute("SELECT ts, rx, tx FROM optics WHERE device=? AND iface=? AND ts>=? ORDER BY ts",
                                    (device, iface, since))
            return cur.fetchall()

    def trends(self, device: str, hours: float = 24) -> dict:
        """{iface: (first_rx, last_rx, delta_db, samples)} over the window."""
        since = time.time() - hours * 3600
        with self._lock:
            cur = self.conn.execute("SELECT iface, rx FROM optics WHERE device=? AND ts>=? AND rx IS NOT NULL "
                                    "ORDER BY ts", (device, since))
            rows = cur.fetchall()
        first, last, count = {}, {}, {}
        for iface, rx in rows:
            first.setdefault(iface, rx)
            last[iface] = rx
            count[iface] = count.get(iface, 0) + 1
        return {i: (first[i], last[i], round(last[i] - first[i], 2), count[i]) for i in last}

    def prune(self, days: int = 30):
        cutoff = time.time() - days * 86400
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM optics WHERE ts < ?", (cutoff,))

    # --------------------------------------------------------- snapshots
    def save_snapshot(self, device: str, label: str, data: dict, ts: float = None) -> int:
        with self._lock, self.conn:
            cur = self.conn.execute("INSERT INTO snapshots (ts, device, label, data) VALUES (?,?,?,?)",
                                    (ts or time.time(), device, label, json.dumps(data)))
            return cur.lastrowid

    def list_snapshots(self, device: str = None):
        with self._lock:
            if device:
                cur = self.conn.execute("SELECT id, ts, device, label FROM snapshots WHERE device=? ORDER BY ts DESC",
                                        (device,))
            else:
                cur = self.conn.execute("SELECT id, ts, device, label FROM snapshots ORDER BY ts DESC")
            return cur.fetchall()

    def load_snapshot(self, snap_id: int):
        with self._lock:
            row = self.conn.execute("SELECT ts, device, label, data FROM snapshots WHERE id=?", (snap_id,)).fetchone()
        if not row:
            return None
        return {"ts": row[0], "device": row[1], "label": row[2], "ports": json.loads(row[3])}

    def delete_snapshot(self, snap_id: int):
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM snapshots WHERE id=?", (snap_id,))

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


SEVERITY_ORDER = {"down": 0, "warning": 1, None: 2, "up": 3}


def _port_sort(name):
    sp = split_port(name)
    return (sp[1], sp[2], sp[3], sp[4] or -1, sp[0]) if sp else (999, 0, 0, 0, name)


def diff_snapshots(before: dict, after: dict, rx_delta: float = 1.0):
    """Compare two snapshot port maps -> [(iface, change, before_text, after_text, severity_key)]."""
    out = []
    for iface in sorted(set(before) | set(after), key=_port_sort):
        b, a = before.get(iface), after.get(iface)
        if b is None:
            out.append((iface, "New port", "–", _state(a), None))
            continue
        if a is None:
            out.append((iface, "Port missing", _state(b), "–", "down"))
            continue
        if b.get("admin") != a.get("admin") and a.get("admin"):
            out.append((iface, "Admin " + ("enabled" if a["admin"] == "up" else "disabled"),
                        (b.get("admin") or "–").capitalize(), a["admin"].capitalize(),
                        "up" if a["admin"] == "up" else "warning"))
        if b.get("link") != a.get("link") and a.get("link"):
            went_down = a["link"] == "down"
            out.append((iface, "Link went DOWN" if went_down else "Link came UP",
                        (b.get("link") or "–").capitalize(), a["link"].capitalize(),
                        "down" if went_down else "up"))
        bf, af = b.get("last_flapped"), a.get("last_flapped")
        if af and af != "Never" and bf != af:
            out.append((iface, "Flapped", bf or "–", af, "warning"))
        brx, arx = b.get("rx"), a.get("rx")
        if brx is not None and arx is None:
            out.append((iface, "Optic reading lost", f"{brx:.2f} dBm", "–", "down"))
        elif brx is None and arx is not None:
            out.append((iface, "Optic reading appeared", "–", f"{arx:.2f} dBm", None))
        elif brx is not None and arx is not None and abs(arx - brx) >= rx_delta:
            sev = "down" if a.get("health") in ("Critical", "No Light") else ("warning" if arx < brx else "up")
            word = "dropped" if arx < brx else "rose"
            out.append((iface, f"Rx {word} {abs(arx - brx):.1f} dB", f"{brx:.2f} dBm", f"{arx:.2f} dBm", sev))
        elif b.get("health") != a.get("health") and a.get("health") in ("Warning", "Critical", "No Light"):
            out.append((iface, f"Optics now {a['health']}", b.get("health") or "–", a["health"], "warning"))
    out.sort(key=lambda r: (SEVERITY_ORDER.get(r[4], 2), _port_sort(r[0])))
    return out


def _state(p):
    if not p:
        return "–"
    return f"{(p.get('admin') or '?').capitalize()}/{(p.get('link') or '?').capitalize()}"
