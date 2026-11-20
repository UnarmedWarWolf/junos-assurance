"""Junos Assurance – GUI for Junos switches reached through a bastion host.

Run:  python3 main.py
"""
import sys

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from app.config import APP_DIR, APP_NAME, Config
from app.main_window import MainWindow
from app.theme import COLORS, STYLESHEET


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
    pal = QPalette()
    for role, col in ((QPalette.ColorRole.Window, COLORS["page"]), (QPalette.ColorRole.Base, "#FFFFFF"),
                      (QPalette.ColorRole.AlternateBase, "#FAFBFC"), (QPalette.ColorRole.Text, COLORS["text"]),
                      (QPalette.ColorRole.WindowText, COLORS["text"]), (QPalette.ColorRole.Button, "#FFFFFF"),
                      (QPalette.ColorRole.ButtonText, COLORS["text"]), (QPalette.ColorRole.Highlight, COLORS["accent"]),
                      (QPalette.ColorRole.HighlightedText, "#FFFFFF"), (QPalette.ColorRole.ToolTipBase, "#FFFFFF"),
                      (QPalette.ColorRole.ToolTipText, COLORS["text"])):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    font = QFont()
    if sys.platform == "win32":
        font.setFamilies(["Segoe UI", "Arial"])
        font.setPointSize(9)
    else:
        font.setFamilies(["Helvetica Neue", "Segoe UI", "Arial"])
        font.setPointSize(13 if sys.platform == "darwin" else 10)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)

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

    win = MainWindow(Config())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
