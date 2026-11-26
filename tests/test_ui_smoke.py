"""PySide6 UI smoke tests using pytest-qt."""

from app.config import AppSettings
from app.core.chem_resolver import ChemResolver
from app.db.database import init_db
from app.db.repository import LCSSRepository
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


def test_sds_view_combo_selection_and_reload_preserves_item(qtbot, tmp_path):
    settings = AppSettings(initialized=True, db_path=str(tmp_path / "sds_combo.db"))
    db = init_db(settings.db_path)
    resolver = ChemResolver()
    with db.get_session() as session:
        repo = LCSSRepository(session)
        repo.upsert_chemical(resolver.resolve_offline("64-17-5"))   # 乙醇
        repo.upsert_chemical(resolver.resolve_offline("119-26-6"))  # DNPH

    win = MainWindow(db, settings)
    qtbot.addWidget(win)
    sds_view = win.sds_view
    assert sds_view.chem_combo.count() == 2

    # Select DNPH explicitly
    dnph_idx = next(
        i for i in range(sds_view.chem_combo.count()) if "119-26-6" in sds_view.chem_combo.itemText(i)
    )
    sds_view.chem_combo.setCurrentIndex(dnph_idx)
    assert "119-26-6" in sds_view.active_chem_banner.text()
    assert "3380" in sds_view.un_no_edit.text()

    # Reload must preserve DNPH selection instead of resetting to index 0 (Ethanol)
    sds_view.reload_chemicals()
    assert sds_view.chem_combo.currentIndex() == dnph_idx
    assert "119-26-6" in sds_view.active_chem_banner.text()
