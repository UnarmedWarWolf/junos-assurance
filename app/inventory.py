"""Saved device inventory (inventory.json in the settings folder) with CSV import/export."""
import csv
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

FIELDS = ["hostname", "site", "role", "tags", "notes"]


@dataclass
class Device:
    hostname: str
    site: str = ""
    role: str = ""
    tags: str = ""
    notes: str = ""
    favorite: bool = False
    last_connected: float = 0.0
    health: int = field(default=-1)   # last known health score, -1 = unknown

    def matches(self, q: str) -> bool:
        q = q.lower().strip()
        if not q:
            return True
        hay = " ".join([self.hostname, self.site, self.role, self.tags, self.notes]).lower()
        return all(part in hay for part in q.split())

    def subtitle(self) -> str:
        return " · ".join(x for x in (self.site, self.role, self.tags) if x)


class Inventory:
    def __init__(self, path):
        self.path = Path(path)
        self.devices = {}
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for d in data:
                dev = Device(**{k: v for k, v in d.items() if k in Device.__dataclass_fields__})
                self.devices[dev.hostname.lower()] = dev
        except Exception:
            pass

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(d) for d in self.devices.values()], indent=2), encoding="utf-8")
        except Exception:
            pass

    def get(self, hostname):
        return self.devices.get((hostname or "").strip().lower())

    def upsert(self, dev: Device, old_hostname: str = None):
        if old_hostname and old_hostname.lower() != dev.hostname.lower():
            self.devices.pop(old_hostname.lower(), None)
        self.devices[dev.hostname.strip().lower()] = dev
        self.save()

    def remove(self, hostname):
        self.devices.pop((hostname or "").lower(), None)
        self.save()

    def touch(self, hostname, health=None):
        """Record a connection (adds the device if new)."""
        hostname = hostname.strip()
        if not hostname:
            return
        dev = self.get(hostname) or Device(hostname=hostname)
        dev.last_connected = time.time()
        if health is not None:
            dev.health = int(health)
        self.devices[hostname.lower()] = dev
        self.save()

    def set_health(self, hostname, score):
        dev = self.get(hostname)
        if dev and dev.health != int(score):
            dev.health = int(score)
            self.save()

    def toggle_favorite(self, hostname):
        dev = self.get(hostname)
        if dev:
            dev.favorite = not dev.favorite
            self.save()

    def search(self, query=""):
        """Favorites first, then most recently connected, then by name."""
        found = [d for d in self.devices.values() if d.matches(query)]
        return sorted(found, key=lambda d: (not d.favorite, -d.last_connected, d.hostname.lower()))

    def import_csv(self, path) -> int:
        """CSV with columns hostname, site, role, tags, notes (header row optional). Returns devices added/updated."""
        n = 0
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            return 0
        header = [h.strip().lower() for h in rows[0]]
        if "hostname" in header:
            idx = {f: header.index(f) for f in FIELDS if f in header}
            rows = rows[1:]
        else:
            idx = {f: i for i, f in enumerate(FIELDS)}
        for r in rows:
            vals = {f: (r[i].strip() if i < len(r) else "") for f, i in idx.items()}
            if not vals.get("hostname"):
                continue
            dev = self.get(vals["hostname"]) or Device(hostname=vals["hostname"])
            for f in FIELDS[1:]:
                if vals.get(f):
                    setattr(dev, f, vals[f])
            self.devices[dev.hostname.lower()] = dev
            n += 1
        self.save()
        return n

    def export_csv(self, path):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(FIELDS + ["favorite"])
            for d in self.search():
                w.writerow([d.hostname, d.site, d.role, d.tags, d.notes, "yes" if d.favorite else ""])
