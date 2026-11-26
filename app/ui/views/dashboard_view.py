"""Dashboard view: chemical safety overview, control-level summary, and cabinet conflict alerts."""

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
from app.schemas import CompatibilityLevel, ControlLevel


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
    """Home dashboard showing chemical safety KPIs and storage compatibility alerts."""

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
        title = QLabel("安全檢查與指引總覽")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        self.refresh_btn = QPushButton("重新整理")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        cards_row = QHBoxLayout()
        self.card_total = StatCard("已建檔化學品數", "#1e3a8a")
        self.card_controlled = StatCard("教師專管 / 禁用藥品", "#d97706")
        self.card_locations = StatCard("已設定安全櫃位數", "#0f766e")
        self.card_conflicts = StatCard("櫃位安全衝突警示", "#dc2626")
        for c in (self.card_total, self.card_controlled, self.card_locations, self.card_conflicts):
            cards_row.addWidget(c)
        layout.addLayout(cards_row)

        layout.addWidget(QLabel("安全檢查警示明細（櫃位不相容衝突／櫃體屬性不符／管制藥品指引）："))
        self.alert_table = QTableWidget(0, 4)
        self.alert_table.setHorizontalHeaderLabels(["警示類型", "藥品／櫃位", "詳細說明", "安全指引建議"])
        self.alert_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.alert_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.alert_table)

        self.refresh()

    def refresh(self) -> None:
        rows: list[tuple[str, str, str, str]] = []
        with self.db.get_session() as session:
            repo = LCSSRepository(session)
            chemicals = repo.search_chemicals()
            locations = repo.list_locations()

            controlled = [
                c for c in chemicals
                if c.control_level in (ControlLevel.TEACHER_ONLY.value, ControlLevel.PROHIBITED.value)
            ]

            conflict_count = 0
            for loc in locations:
                items = repo.get_items_in_location(loc.id)
                for it in items:
                    if not it.chemical:
                        continue
                    groups, _, _ = self.compat_engine.classify_reactive_groups(
                        it.chemical.cas_number, it.chemical.smiles, it.chemical.reactive_groups
                    )
                    cab_res = self.compat_engine.check_cabinet_suitability(
                        it.chemical.ghs_pictograms, groups, loc.cabinet_type
                    )
                    if not cab_res.compatible:
                        conflict_count += 1
                        name = it.chemical.name_zh or it.chemical.name_en
                        rows.append(("櫃體屬性不符", f"{loc.display_name} ({name})", cab_res.message_zh, "請移至符合屬性之藥品櫃"))

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
                        conflict_count += 1
                        rows.append((
                            "櫃位不相容",
                            f"{loc.display_name} ({issue.chem_a_name} × {issue.chem_b_name})",
                            issue.summary_zh,
                            "禁止混放，請立即分櫃隔離",
                        ))

            for c in controlled:
                label = "禁用藥品" if c.control_level == ControlLevel.PROHIBITED.value else "教師專管"
                rows.append((
                    label,
                    f"{c.name_zh or c.name_en} ({c.cas_number})",
                    "具高毒、致癌、爆炸或法規管制風險",
                    "須上鎖專櫃管理並於操作前確認安全防護",
                ))

        self.card_total.set_value(len(chemicals))
        self.card_controlled.set_value(len(controlled))
        self.card_locations.set_value(len(locations))
        self.card_conflicts.set_value(conflict_count)

        self.alert_table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.alert_table.setItem(r_idx, c_idx, item)
