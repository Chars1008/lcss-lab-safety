"""Dashboard view: overview of expiring chemicals, low stock, and cabinet conflicts."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import AppSettings
from app.core.compatibility import CompatibilityEngine
from app.db.database import DatabaseManager
from app.db.repository import LCSSRepository
from app.schemas import CompatibilityLevel, ItemStatus


class StatCard(QFrame):
    """Simple summary card widget."""

    def __init__(self, title: str, color: str = "#1e3a8a", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"QFrame {{ background: #ffffff; border: 1px solid #e5e7eb; border-top: 4px solid {color}; border-radius: 6px; padding: 10px; }}"
        )
        layout = QVBoxLayout(self)
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet("color: #4b5563; font-size: 10pt; border: none;")
        self.value_lbl = QLabel("0")
        self.value_lbl.setStyleSheet(f"color: {color}; font-size: 20pt; font-weight: bold; border: none;")
        layout.addWidget(self.title_lbl)
        layout.addWidget(self.value_lbl)

    def set_value(self, value: int | str) -> None:
        self.value_lbl.setText(str(value))


class DashboardView(QWidget):
    """Home dashboard showing lab safety KPIs and alerts."""

    def __init__(
        self,
        db: DatabaseManager,
        settings: AppSettings,
        compat_engine: CompatibilityEngine,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.compat_engine = compat_engine

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("安全總覽儀表板")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        self.refresh_btn = QPushButton("重新整理")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        cards_row = QHBoxLayout()
        self.card_total = StatCard("在庫總瓶數", "#1e3a8a")
        self.card_expiring = StatCard("即期 / 已過期 (30天內)", "#d97706")
        self.card_low = StatCard("低庫存警示", "#2563eb")
        self.card_conflicts = StatCard("櫃位不相容衝突", "#dc2626")
        for c in (self.card_total, self.card_expiring, self.card_low, self.card_conflicts):
            cards_row.addWidget(c)
        layout.addLayout(cards_row)

        layout.addWidget(QLabel("警示明細（即期／低庫存／櫃位衝突）："))
        self.alert_table = QTableWidget(0, 4)
        self.alert_table.setHorizontalHeaderLabels(["警示類型", "藥品／櫃位", "詳細說明", "建議處置"])
        self.alert_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.alert_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.alert_table)

        self.refresh()

    def refresh(self) -> None:
        with self.db.get_session() as session:
            repo = LCSSRepository(session)
            in_stock = repo.list_inventory_items(status=ItemStatus.IN_STOCK.value)
            expiring = repo.list_expiring_items(within_days=self.settings.expiry_warning_days)
            low_stock = repo.list_low_stock_items(threshold_ratio=self.settings.low_stock_threshold_ratio)
            locations = repo.list_locations()

            conflicts: list[tuple[str, str, str]] = []
            for loc in locations:
                items = repo.get_items_in_location(loc.id)
                if len(items) < 2:
                    continue
                chems = [
                    {
                        "cas_number": it.chemical.cas_number,
                        "name_zh": it.chemical.name_zh,
                        "name_en": it.chemical.name_en,
                        "smiles": it.chemical.smiles,
                        "reactive_groups": it.chemical.reactive_groups,
                    }
                    for it in items
                    if it.chemical
                ]
                for issue in self.compat_engine.check_matrix(chems):
                    if issue.level == CompatibilityLevel.INCOMPATIBLE:
                        conflicts.append((loc.display_name, f"{issue.chem_a_name} × {issue.chem_b_name}", issue.summary_zh))

        self.card_total.set_value(len(in_stock))
        self.card_expiring.set_value(len(expiring))
        self.card_low.set_value(len(low_stock))
        self.card_conflicts.set_value(len(conflicts))

        rows: list[tuple[str, str, str, str]] = []
        for loc_name, pair, summary in conflicts:
            rows.append(("櫃位不相容", f"{loc_name} ({pair})", summary, "請立即分櫃隔離存放"))
        for it in expiring:
            name = it.chemical.name_zh or it.chemical.name_en if it.chemical else it.barcode
            rows.append(("效期警示", f"{name} [{it.barcode}]", f"有效期限：{it.expiry_date}", "請確認品質或安排報廢"))
        for it in low_stock:
            name = it.chemical.name_zh or it.chemical.name_en if it.chemical else it.barcode
            rows.append(("低庫存", f"{name} [{it.barcode}]", f"剩餘 {it.current_quantity}/{it.capacity} {it.unit}", "評估請購補充"))

        self.alert_table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.alert_table.setItem(r_idx, c_idx, item)
