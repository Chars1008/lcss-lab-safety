"""Application entrypoint for Laboratory Chemical Safety System (LCSS)."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen


def main() -> int:
    """Initialize settings, database, optional first-run wizard, and main window."""
    app = QApplication(sys.argv)
    app.setApplicationName("勤思實驗室藥品安全管理系統(GLCSS)")

    # Show immediate splash screen while RDKit / SQLAlchemy / PyMuPDF initialize
    pix = QPixmap(420, 150)
    pix.fill(QColor("#1e3a8a"))
    splash = QSplashScreen(pix)
    splash.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
    splash.showMessage(
        "勤思實驗室藥品安全管理系統 (GLCSS)\n\n正在載入化學安全引擎與資料庫，請稍候...",
        Qt.AlignmentFlag.AlignCenter,
        QColor("#ffffff"),
    )
    splash.show()
    app.processEvents()

    from app.config import AppSettings
    from app.db.database import DatabaseManager
    from app.ui.main_window import MainWindow
    from app.ui.setup_wizard import SetupWizard

    settings = AppSettings.load()
    settings.ensure_directories()

    db = DatabaseManager(settings.db_path)
    db.init_db()

    if not settings.initialized:
        splash.close()
        wizard = SetupWizard(db, settings)
        wizard.raise_()
        wizard.activateWindow()
        if wizard.exec() != SetupWizard.DialogCode.Accepted:
            return 0

    window = MainWindow(db, settings)
    window.show()
    window.raise_()
    window.activateWindow()
    splash.finish(window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
