"""PySide6 UI smoke tests using pytest-qt."""

from app.config import AppSettings
from app.db.database import init_db
from app.ui.main_window import MainWindow
from app.ui.setup_wizard import SetupWizard


def test_main_window_smoke(qtbot, tmp_path):
    settings = AppSettings(
        initialized=True,
        db_path=str(tmp_path / "test.db"),
    )
    db = init_db(settings.db_path)
    win = MainWindow(db, settings)
    qtbot.addWidget(win)
    win.show()

    assert win.nav_list.count() == 5
    for idx in range(5):
        win.nav_list.setCurrentRow(idx)
        assert win.stack.currentIndex() == idx


def test_setup_wizard_smoke(qtbot, tmp_path):
    settings = AppSettings(
        initialized=False,
        db_path=str(tmp_path / "wiz.db"),
    )
    db = init_db(settings.db_path)
    wiz = SetupWizard(db, settings)
    qtbot.addWidget(wiz)
    assert len(wiz.pageIds()) == 4
