"""Junos Assurance – GUI for Junos switches reached through a jump host.

Run:  python3 main.py
"""
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.config import APP_DIR, APP_NAME, Config
from app.main_window import MainWindow
from app.theme import apply_theme


def main():
    if sys.platform == "win32":
        try:  # own taskbar entry/icon instead of being grouped under python.exe
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JunosAssurance.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    cfg = Config()
    apply_theme(app, bool(cfg["dark_mode"]))
    font = QFont()
    if sys.platform == "win32":
        font.setFamilies(["Segoe UI", "Arial"])
        font.setPointSize(9)
    else:
        font.setFamilies(["Helvetica Neue", "Segoe UI", "Arial"])
        font.setPointSize(13 if sys.platform == "darwin" else 10)
    app.setFont(font)

    def excepthook(etype, value, tb):   # log unexpected errors instead of failing silently (pythonw/.exe)
        import traceback
        from PySide6.QtWidgets import QMessageBox
        text = "".join(traceback.format_exception(etype, value, tb))
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            with open(APP_DIR / "error.log", "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except Exception:
            pass
        QMessageBox.critical(None, APP_NAME, f"Unexpected error (details in {APP_DIR / 'error.log'}):\n\n{value}")
    sys.excepthook = excepthook

    app.setQuitOnLastWindowClosed(True)
    win = MainWindow(cfg)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
