"""Tests for SQLAlchemy repository CRUD, inventory lifecycle, and audit logs."""

from datetime import date, timedelta

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
