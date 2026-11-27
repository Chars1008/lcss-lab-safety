"""Compatibility view: cabinet safety audit + interactive N x N free compatibility matrix."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.compatibility import CompatibilityEngine
from app.db.database import DatabaseManager
from app.db.repository import LCSSRepository
from app.schemas import CompatibilityIssue, CompatibilityLevel


class CompatibilityView(QWidget):
    """Interactive N x N compatibility matrix checker with cabinet filtering."""

    def __init__(
        self,
        db: DatabaseManager,
        compat_engine: CompatibilityEngine,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.compat_engine = compat_engine
        self._issue_lookup: dict[tuple[int, int], CompatibilityIssue] = {}

        layout = QVBoxLayout(self)
        title = QLabel("化學相容性檢查矩陣（N × N 互動檢查器）")
        title.setStyleSheet("font-size: 15pt; font-weight: bold;")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Filter by cabinet + Select 2..15 chemicals
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("依存放櫃位篩選："))
        self.cabinet_filter_combo = QComboBox()
        self.cabinet_filter_combo.currentIndexChanged.connect(self._on_cabinet_filter_changed)
        left_layout.addWidget(self.cabinet_filter_combo)

        left_layout.addWidget(QLabel("勾選 2～15 種化學品："))
        self.chem_list = QListWidget()
        self.chem_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        left_layout.addWidget(self.chem_list)

        btn_row = QHBoxLayout()
        reload_btn = QPushButton("重新載入")
        reload_btn.clicked.connect(self.reload_chemicals)
        select_all_btn = QPushButton("全選並檢查")
        select_all_btn.clicked.connect(self._select_all_and_check)
        check_btn = QPushButton("產生 N × N 矩陣")
        check_btn.setStyleSheet("background: #1e3a8a; color: #fff; font-weight: bold; padding: 6px;")
        check_btn.clicked.connect(self.run_matrix)
        btn_row.addWidget(reload_btn)
        btn_row.addWidget(select_all_btn)
        btn_row.addWidget(check_btn)
        left_layout.addLayout(btn_row)
        splitter.addWidget(left)

        # Right: Matrix table + detail panel
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.matrix_table = QTableWidget(0, 0)
        self.matrix_table.cellClicked.connect(self._on_cell_clicked)
        right_layout.addWidget(self.matrix_table, 3)

        right_layout.addWidget(QLabel("點擊任一儲存格檢視反應機制與隔離建議："))
        self.detail_box = QTextEdit()
        self.detail_box.setReadOnly(True)
        self.detail_box.setMaximumHeight(160)
        right_layout.addWidget(self.detail_box, 1)
        splitter.addWidget(right)

        splitter.setSizes([310, 610])
        layout.addWidget(splitter)
        self.reload_chemicals()

    def reload_chemicals(self) -> None:
        prev_loc = self.cabinet_filter_combo.currentData()
        self.cabinet_filter_combo.blockSignals(True)
        self.cabinet_filter_combo.clear()
        self.cabinet_filter_combo.addItem("全部已建檔化學品", "ALL")
        with self.db.get_session() as session:
            for loc in LCSSRepository(session).list_locations():
                self.cabinet_filter_combo.addItem(f"{loc.display_name} [{loc.cabinet_type}]", loc.id)
        if prev_loc is not None:
            idx = self.cabinet_filter_combo.findData(prev_loc)
            if idx >= 0:
                self.cabinet_filter_combo.setCurrentIndex(idx)
        self.cabinet_filter_combo.blockSignals(False)
        self._on_cabinet_filter_changed()

    def _on_cabinet_filter_changed(self) -> None:
        loc_id = self.cabinet_filter_combo.currentData()
        self.chem_list.clear()
        with self.db.get_session() as session:
            repo = LCSSRepository(session)
            if isinstance(loc_id, int):
                items = repo.get_items_in_location(loc_id)
                seen: set[int] = set()
                chems = []
                for it in items:
                    if it.chemical and it.chemical.id not in seen:
                        seen.add(it.chemical.id)
                        chems.append(it.chemical)
            else:
                chems = repo.search_chemicals()

        for c in chems:
            label = f"{c.name_zh or c.name_en} ({c.cas_number})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, {
                "cas_number": c.cas_number,
                "name_zh": c.name_zh,
                "name_en": c.name_en,
                "smiles": c.smiles,
                "reactive_groups": c.reactive_groups,
                "ghs_pictograms": c.ghs_pictograms,
                "h_codes": c.h_codes,
                "sds_json": c.sds_json,
            })
            self.chem_list.addItem(item)

    def _select_all_and_check(self) -> None:
        for i in range(min(self.chem_list.count(), 15)):
            self.chem_list.item(i).setSelected(True)
        self.run_matrix()

    def run_matrix(self) -> None:
        selected: list[dict[str, Any]] = [
            it.data(Qt.ItemDataRole.UserRole) for it in self.chem_list.selectedItems()
        ]
        if len(selected) < 2:
            self.detail_box.setPlainText("請至少選擇 2 種化學品（若此櫃位不足 2 種藥品則無混放衝突）。")
            self.matrix_table.setRowCount(0)
            self.matrix_table.setColumnCount(0)
            return
        if len(selected) > 15:
            selected = selected[:15]

        n = len(selected)
        names = [c["name_zh"] or c["name_en"] or c["cas_number"] for c in selected]
        self.matrix_table.setRowCount(n)
        self.matrix_table.setColumnCount(n)
        self.matrix_table.setHorizontalHeaderLabels(names)
        self.matrix_table.setVerticalHeaderLabels(names)
        self._issue_lookup.clear()

        for i in range(n):
            for j in range(n):
                if i == j:
                    cell = QTableWidgetItem("—")
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    cell.setBackground(QColor("#f3f4f6"))
                    cell.setForeground(QColor("#374151"))
                    self.matrix_table.setItem(i, j, cell)
                    continue
                issue = self.compat_engine.check_pair(selected[i], selected[j])
                self._issue_lookup[(i, j)] = issue
                if issue.level == CompatibilityLevel.INCOMPATIBLE:
                    text, bg, fg = "禁混", QColor("#fecaca"), QColor("#7f1d1d")
                elif issue.level == CompatibilityLevel.CAUTION:
                    text, bg, fg = "警示", QColor("#fde68a"), QColor("#78350f")
                elif issue.level == CompatibilityLevel.UNKNOWN:
                    text, bg, fg = "未知", QColor("#e5e7eb"), QColor("#1f2937")
                else:
                    text, bg, fg = "相容", QColor("#bbf7d0"), QColor("#14532d")
                cell = QTableWidgetItem(text)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setBackground(bg)
                cell.setForeground(fg)
                font = cell.font()
                font.setBold(issue.level in (CompatibilityLevel.INCOMPATIBLE, CompatibilityLevel.CAUTION))
                cell.setFont(font)
                self.matrix_table.setItem(i, j, cell)

    def _on_cell_clicked(self, row: int, col: int) -> None:
        issue = self._issue_lookup.get((row, col))
        if not issue:
            self.detail_box.setPlainText("同一化學品無須比較。")
            return
        lines = [
            f"配對：{issue.chem_a_name} ({issue.chem_a_cas}) × {issue.chem_b_name} ({issue.chem_b_cas})",
            f"判定等級：{issue.level.value}",
            f"危害標籤：{', '.join(issue.hazards) or '無'}",
            f"機制說明：{issue.summary_zh}",
            f"建議處置：{issue.recommendation_zh}",
        ]
        if issue.inference_note:
            lines.append(f"推斷註記：{issue.inference_note}")
        self.detail_box.setPlainText("\n".join(lines))
