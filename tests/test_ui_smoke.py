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

    # Language selector supports zh-TW and en
    langs = [sds_view.lang_combo.itemData(i) for i in range(sds_view.lang_combo.count())]
    assert langs == ["zh-TW", "en"]


def test_settings_view_ollama_combo_and_location_table(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(AppSettings, "save", lambda self, path=None: tmp_path / "settings.json")
    settings = AppSettings(initialized=True, db_path=str(tmp_path / "settings_ui.db"))
    db = init_db(settings.db_path)
    with db.get_session() as session:
        LCSSRepository(session).create_location("化學室", "酸鹼櫃", "第 1 層", "CORROSIVE")

    win = MainWindow(db, settings)
    qtbot.addWidget(win)
    sv = win.settings_view
    sv.reload_locations_table()
    assert sv.loc_table.rowCount() == 1

    # Ollama combo has default models and updates llm_service immediately on selection
    assert sv.ollama_model_combo.count() >= 4
    sv.ollama_model_combo.setCurrentText("gemma2:9b")
    assert win.llm_service.model == "gemma2:9b"
    assert settings.ollama_model == "gemma2:9b"


def test_manual_entry_filters_cabinet_matrix_and_saved_sds_list(qtbot, tmp_path):
    settings = AppSettings(initialized=True, db_path=str(tmp_path / "feat.db"))
    db = init_db(settings.db_path)
    resolver = ChemResolver()

    with db.get_session() as session:
        repo = LCSSRepository(session)
        loc_acid = repo.create_location("化研室", "耐酸鹼櫃", "第 1 層", "CORROSIVE")
        loc_flam = repo.create_location("化研室", "易燃櫃", "第 1 層", "FLAMMABLE")
        hcl = repo.upsert_chemical(resolver.resolve_offline("7647-01-0"))
        bleach = repo.upsert_chemical(resolver.resolve_offline("7681-52-9"))
        eth = repo.upsert_chemical(resolver.resolve_offline("64-17-5"))
        repo.check_in_item(hcl.id, loc_acid.id, 1.0)
        repo.check_in_item(bleach.id, loc_acid.id, 1.0)
        repo.check_in_item(eth.id, loc_flam.id, 1.0)

    win = MainWindow(db, settings)
    qtbot.addWidget(win)

    # 1. InventoryView: manual entry & multi-column filters
    iv = win.inventory_view
    iv.reload_locations()
    iv.refresh_table()
    assert iv.table.rowCount() == 3

    # Filter by cabinet -> only 2 items in loc_acid
    idx_acid = iv.filter_loc_combo.findData(loc_acid.id)
    iv.filter_loc_combo.setCurrentIndex(idx_acid)
    assert iv.table.rowCount() == 2

    # Manual chemical creation without online lookup
    iv._clear_form()
    iv.edit_cas.setText("999-99-9")
    iv.edit_name_zh.setText("自建測試試劑")
    iv.edit_smiles.setText("CCO")
    edited = iv._collect_edited_chemical()
    assert edited is not None and edited.name_zh == "自建測試試劑"

    # 2. CompatibilityView: filter by loc_acid and run one-click check -> INCOMPATIBLE
    cv = win.compatibility_view
    cv.reload_chemicals()
    idx_cv_acid = cv.cabinet_filter_combo.findData(loc_acid.id)
    cv.cabinet_filter_combo.setCurrentIndex(idx_cv_acid)
    assert cv.chem_list.count() == 2
    cv._select_all_and_check()
    assert cv.matrix_table.rowCount() == 2
    assert cv.matrix_table.item(0, 1).text() == "禁混"

    # 3. SDSView: saved_sds_table lists all chemicals and clicking switches editor
    sv = win.sds_view
    sv.reload_chemicals()
    assert sv.saved_sds_table.rowCount() == 3
    sv.saved_sds_table.selectRow(1)
    assert sv.chem_combo.currentData() is not None
