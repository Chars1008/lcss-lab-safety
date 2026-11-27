"""Application entrypoint for 勤思實驗室藥品安全管理系統(GLCSS)."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen


def main() -> int:
    """Initialize settings, database, optional first-run wizard, and main window."""
    app = QApplication(sys.argv)
    app.setApplicationName("勤思實驗室藥品安全管理系統(GLCSS)")
    icon_file = Path(__file__).resolve().parent / "data" / "icons" / "app_icon.png"
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))
    # Prevent splash.close() from triggering quitOnLastWindowClosed before wizard/main window shows
    app.setQuitOnLastWindowClosed(False)

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

    try:
        from app.config import AppSettings, STORAGE_DIR
        from app.db.database import DatabaseManager
        from app.ui.main_window import MainWindow
        from app.ui.setup_wizard import SetupWizard

        settings = AppSettings.load()
        settings.ensure_directories()

        db = DatabaseManager(settings.db_path)
        db.init_db()

        if not settings.initialized:
            wizard = SetupWizard(db, settings)
            wizard.show()
            wizard.raise_()
            wizard.activateWindow()
            splash.finish(wizard)
            if wizard.exec() != SetupWizard.DialogCode.Accepted:
                return 0

        window = MainWindow(db, settings)
        app.setQuitOnLastWindowClosed(True)
        window.show()
        window.raise_()
        window.activateWindow()
        splash.finish(window)
        return app.exec()
    except Exception as exc:
        splash.close()
        err_text = f"{exc}\n\n{traceback.format_exc()}"
        try:
            log_path = Path(__file__).resolve().parent / "storage" / "startup_error.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(err_text, encoding="utf-8")
        except Exception:
            pass
        QMessageBox.critical(None, "GLCSS 啟動錯誤", f"啟動時發生錯誤：\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
