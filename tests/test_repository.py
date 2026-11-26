"""Tests for SQLAlchemy repository CRUD, inventory lifecycle, and audit logs."""

from datetime import date, timedelta

from app.config import AppSettings
from app.core.backup import export_bundle_json, export_inventory_csv, import_bundle_json
from app.core.chem_resolver import ChemResolver
from app.db.database import init_db
from app.db.repository import LCSSRepository
from app.schemas import CabinetType, ItemStatus


def test_inventory_lifecycle_and_alerts():
    db = init_db(":memory:")
    resolver = ChemResolver()
    hcl = resolver.resolve_offline("7647-01-0")
    assert hcl is not None

    with db.get_session() as session:
        repo = LCSSRepository(session)
        chem = repo.upsert_chemical(hcl)
        loc = repo.create_location("生科實驗室", "耐酸鹼櫃 A", "第 1 層", CabinetType.CORROSIVE.value)

        item = repo.check_in_item(
            chemical_id=chem.id,
            location_id=loc.id,
            capacity=500.0,
            unit="mL",
            brand="Sigma",
            expiry_date=date.today() + timedelta(days=10),
        )
        assert item.status == ItemStatus.IN_STOCK.value
        assert len(repo.list_expiring_items(within_days=30)) == 1

        # Check out 450 mL -> 50 mL remaining (10% <= 20% low stock)
        updated = repo.check_out_quantity(item.id, 450.0)
        assert updated is not None
        assert updated.current_quantity == 50.0
        assert len(repo.list_low_stock_items(threshold_ratio=0.2)) == 1

        # Dispose
        disposed = repo.dispose_item(item.id)
        assert disposed is not None
        assert disposed.status == ItemStatus.DISPOSED.value
        assert disposed.current_quantity == 0.0


def test_location_update_delete_and_backup_restore(tmp_path):
    db_src = init_db(tmp_path / "src.db")
    settings_src = AppSettings(
        initialized=True,
        lab_name="生科一館",
        emergency_phone="03-1234567",
        db_path=str(tmp_path / "src.db"),
    )
    resolver = ChemResolver()
    ethanol = resolver.resolve_offline("64-17-5")
    assert ethanol is not None

    with db_src.get_session() as session:
        repo = LCSSRepository(session)
        chem = repo.upsert_chemical(ethanol)
        loc = repo.create_location("生科一館", "易燃櫃 A", "第 1 層", CabinetType.FLAMMABLE.value)
        repo.update_location(loc.id, "生科一館", "易燃櫃 A-新", "第 2 層", CabinetType.FLAMMABLE.value)
        assert repo.get_location(loc.id).cabinet_name == "易燃櫃 A-新"
        item = repo.check_in_item(chem.id, loc.id, 500.0, barcode="GLCSS-BK01")

    csv_path = export_inventory_csv(db_src, tmp_path / "inv.csv")
    assert csv_path.exists() and "64-17-5" in csv_path.read_text(encoding="utf-8-sig")

    bundle_path = export_bundle_json(db_src, settings_src, tmp_path / "backup.json")
    assert bundle_path.exists()

    # Delete location safely even with item attached
    with db_src.get_session() as session:
        repo = LCSSRepository(session)
        assert repo.delete_location(loc.id) is True
        assert repo.get_item_by_barcode(item.barcode).location_id is None

    # Restore into fresh DB
    db_dst = init_db(tmp_path / "dst.db")
    settings_dst = AppSettings(db_path=str(tmp_path / "dst.db"))
    counts = import_bundle_json(db_dst, settings_dst, bundle_path)
    assert counts["locations"] == 1
    assert counts["chemicals"] == 1
    assert counts["items"] == 1
    assert settings_dst.lab_name == "生科一館"
