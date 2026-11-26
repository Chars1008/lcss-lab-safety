"""Application entrypoint for Laboratory Chemical Safety System (LCSS)."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.config import AppSettings
from app.db.database import DatabaseManager
from app.ui.main_window import MainWindow
from app.ui.setup_wizard import SetupWizard


def main() -> int:
    """Initialize settings, database, optional first-run wizard, and main window."""
    app = QApplication(sys.argv)
    app.setApplicationName("Laboratory Chemical Safety System (LCSS)")

    settings = AppSettings.load()
    settings.ensure_directories()

    db = DatabaseManager(settings.db_path)
    db.init_db()

    if not settings.initialized:
        wizard = SetupWizard(db, settings)
        if wizard.exec() != SetupWizard.DialogCode.Accepted:
            return 0

    window = MainWindow(db, settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
