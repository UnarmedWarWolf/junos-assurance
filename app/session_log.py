"""Automatic per-session text logs: <log folder>/<YYYY-MM-DD>/<device>_<HHMMSS>.log"""
import re
from datetime import datetime
from pathlib import Path


def default_log_dir() -> Path:
    return Path.home() / "Documents" / "JunosAssurance Logs"


class SessionLogger:
    def __init__(self, folder, device: str, user: str = "", jump_host: str = ""):
        now = datetime.now()
        safe = re.sub(r"[^\w.-]", "_", device or "device")
        self.path = Path(folder) / now.strftime("%Y-%m-%d") / f"{safe}_{now:%H%M%S}.log"
        self._fh = None
        self._header = (f"# Junos Assurance session log\n# Device: {device}\n# User: {user}\n"
                        f"# Jump host: {jump_host}\n# Started: {now:%Y-%m-%d %H:%M:%S}\n\n")

    def _open(self):
        if self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a", encoding="utf-8")
            self._fh.write(self._header)
        return self._fh

    def write(self, text: str):
        try:
            fh = self._open()
            fh.write(text)
            fh.flush()
        except Exception:
            pass

    def mark(self, command: str):
        """Timestamp each command the user sends (log file only)."""
        self.write(f"\n# [{datetime.now():%H:%M:%S}] > {command}\n")

    def close(self):
        if self._fh:
            try:
                self._fh.write(f"\n# Ended: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                self._fh.close()
            except Exception:
                pass
            self._fh = None
