"""Chemical safety registry & cabinet placement check view (no inventory quantity tracking)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.chem_resolver import ChemResolver, validate_cas_checksum
from app.core.compatibility import CompatibilityEngine
from app.db.database import DatabaseManager
from app.db.repository import LCSSRepository
from app.schemas import CompatibilityLevel, ItemStatus, ResolvedChemical
from app.ui.widgets.common import CompatibilityWarningDialog, GHSPictogramStrip, MoleculePreviewWidget
from app.ui.workers import AsyncWorker


class InventoryView(QWidget):
    """Chemical master resolution + cabinet placement compatibility safety check."""

    def __init__(
        self,
        db: DatabaseManager,
        resolver: ChemResolver,
        compat_engine: CompatibilityEngine,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.resolver = resolver
        self.compat_engine = compat_engine
        self.thread_pool = QThreadPool.globalInstance()
        self._current_resolved: Optional[ResolvedChemical] = None

        main_layout = QHBoxLayout(self)

        # Left: Registered chemicals & their assigned safety cabinet
        left_panel = QVBoxLayout()
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜尋已建檔藥品名稱 / CAS...")
        self.search_input.returnPressed.connect(self.refresh_table)
        search_btn = QPushButton("搜尋")
        search_btn.clicked.connect(self.refresh_table)
        search_row.addWidget(self.search_input)
        search_row.addWidget(search_btn)
        left_panel.addLayout(search_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["中文品名", "英文品名", "CAS No.", "警示語", "配置櫃位"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        left_panel.addWidget(self.table)

        action_row = QHBoxLayout()
        remove_btn = QPushButton("從櫃位移除選取紀錄")
        remove_btn.clicked.connect(self._on_remove_placement)
        action_row.addWidget(remove_btn)
        action_row.addStretch(1)
        left_panel.addLayout(action_row)
        main_layout.addLayout(left_panel, 3)

        # Right: Chemical resolution & cabinet safety placement check
        right_box = QGroupBox("藥品解析與櫃位安全檢查（不管理庫存數量）")
        right_layout = QVBoxLayout(right_box)

        cas_row = QHBoxLayout()
        self.cas_input = QLineEdit()
        self.cas_input.setPlaceholderText("輸入 CAS（例：7647-01-0）或英文品名")
        self.resolve_btn = QPushButton("線上／離線解析")
        self.resolve_btn.clicked.connect(self._on_resolve)
        cas_row.addWidget(self.cas_input)
        cas_row.addWidget(self.resolve_btn)
        right_layout.addLayout(cas_row)

        self.resolved_lbl = QLabel("尚未解析藥品")
        self.resolved_lbl.setWordWrap(True)
        right_layout.addWidget(self.resolved_lbl)

        self.ghs_strip = GHSPictogramStrip()
        right_layout.addWidget(self.ghs_strip)

        self.mol_preview = MoleculePreviewWidget()
        right_layout.addWidget(self.mol_preview)

        form = QFormLayout()
        self.location_combo = QComboBox()
        form.addRow("目標存放櫃位：", self.location_combo)
        right_layout.addLayout(form)

        self.checkin_btn = QPushButton("執行相容性檢查並登錄櫃位")
        self.checkin_btn.setStyleSheet("background: #1e3a8a; color: #fff; font-weight: bold; padding: 8px;")
        self.checkin_btn.clicked.connect(self._on_register_placement)
        right_layout.addWidget(self.checkin_btn)
        right_layout.addStretch(1)

        main_layout.addWidget(right_box, 2)
        self.reload_locations()
        self.refresh_table()

    def reload_locations(self) -> None:
        self.location_combo.clear()
        with self.db.get_session() as session:
            for loc in LCSSRepository(session).list_locations():
                self.location_combo.addItem(f"{loc.display_name} [{loc.cabinet_type}]", loc.id)

    def refresh_table(self) -> None:
        query = self.search_input.text().strip()
        with self.db.get_session() as session:
            items = LCSSRepository(session).list_inventory_items(
                search=query, status=ItemStatus.IN_STOCK.value
            )
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            name_zh = it.chemical.name_zh if it.chemical else ""
            name_en = it.chemical.name_en if it.chemical else ""
            cas = it.chemical.cas_number if it.chemical else ""
            signal = (it.chemical.signal_word or "無") if it.chemical else ""
            loc = it.location.display_name if it.location else "未指定櫃位"
            for c, v in enumerate([name_zh, name_en, cas, signal, loc]):
                cell = QTableWidgetItem(v)
                cell.setData(256, it.id)
                self.table.setItem(r, c, cell)

    def _on_resolve(self) -> None:
        q = self.cas_input.text().strip()
        if not q:
            return
        self.resolve_btn.setEnabled(False)
        self.resolved_lbl.setText("正在背景查詢藥品安全資料...")

        def _task() -> Optional[ResolvedChemical]:
            with self.db.get_session() as session:
                repo = LCSSRepository(session)
                if validate_cas_checksum(q):
                    cached = repo.get_chemical_by_cas(q)
                    if cached:
                        return ResolvedChemical(
                            cas_number=cached.cas_number,
                            name_zh=cached.name_zh,
                            name_en=cached.name_en,
                            formula=cached.formula,
                            molecular_weight=cached.molecular_weight,
                            smiles=cached.smiles,
                            ghs_pictograms=cached.ghs_pictograms,
                            signal_word=cached.signal_word,
                            h_codes=cached.h_codes,
                            p_codes=cached.p_codes,
                            reactive_groups=cached.reactive_groups,
                            data_source="LOCAL_SQLITE_CACHE",
                        )
            return self.resolver.resolve_online(q)

        worker = AsyncWorker(_task)
        worker.signals.finished.connect(self._on_resolved_done)
        worker.signals.error.connect(self._on_resolved_error)
        self.thread_pool.start(worker)

    def _on_resolved_done(self, result: Optional[ResolvedChemical]) -> None:
        self.resolve_btn.setEnabled(True)
        self._current_resolved = result
        if result is None:
            self.resolved_lbl.setText("查無此藥品資料，請確認 CAS 校驗碼或英文名稱。")
            self.ghs_strip.set_pictograms([])
            self.mol_preview.set_smiles("")
            return
        self.resolved_lbl.setText(
            f"<b>{result.name_zh or result.name_en}</b> ({result.name_en})<br>"
            f"CAS: {result.cas_number} ｜ 分子式: {result.formula} ｜ 警示語: {result.signal_word or '無'}<br>"
            f"來源: {result.data_source}"
        )
        self.ghs_strip.set_pictograms(result.ghs_pictograms)
        self.mol_preview.set_smiles(result.smiles)

    def _on_resolved_error(self, err: str) -> None:
        self.resolve_btn.setEnabled(True)
        self.resolved_lbl.setText(f"解析發生錯誤：{err.splitlines()[0]}")

    def _on_register_placement(self) -> None:
        if self._current_resolved is None:
            QMessageBox.warning(self, "提醒", "請先解析藥品資料再進行安全檢查。")
            return
        loc_id = self.location_combo.currentData()
        override_reason = ""

        with self.db.get_session() as session:
            repo = LCSSRepository(session)
            chem = repo.upsert_chemical(self._current_resolved)

            if loc_id is not None:
                loc = repo.get_location(loc_id)
                existing_items = repo.get_items_in_location(loc_id)
                new_dict = {
                    "cas_number": chem.cas_number,
                    "name_zh": chem.name_zh,
                    "name_en": chem.name_en,
                    "smiles": chem.smiles,
                    "reactive_groups": chem.reactive_groups,
                }
                issues = []
                for ex in existing_items:
                    if ex.chemical:
                        ex_dict = {
                            "cas_number": ex.chemical.cas_number,
                            "name_zh": ex.chemical.name_zh,
                            "name_en": ex.chemical.name_en,
                            "smiles": ex.chemical.smiles,
                            "reactive_groups": ex.chemical.reactive_groups,
                        }
                        issue = self.compat_engine.check_pair(new_dict, ex_dict)
                        if issue.level in (CompatibilityLevel.INCOMPATIBLE, CompatibilityLevel.CAUTION):
                            issues.append(issue)

                cab_warn = ""
                if loc:
                    groups, _, _ = self.compat_engine.classify_reactive_groups(
                        chem.cas_number, chem.smiles, chem.reactive_groups
                    )
                    cab_res = self.compat_engine.check_cabinet_suitability(
                        chem.ghs_pictograms, groups, loc.cabinet_type
                    )
                    if not cab_res.compatible:
                        cab_warn = cab_res.message_zh

                if issues or cab_warn:
                    dlg = CompatibilityWarningDialog(issues, cabinet_warning=cab_warn, parent=self)
                    if dlg.exec() != CompatibilityWarningDialog.DialogCode.Accepted:
                        return
                    override_reason = dlg.override_reason

            repo.check_in_item(
                chemical_id=chem.id,
                location_id=loc_id,
                capacity=1.0,
                unit="項",
                override_warning_reason=override_reason,
            )

        self.refresh_table()
        QMessageBox.information(self, "登錄成功", "已完成相容性安全檢查並登錄藥品櫃位。")

    def _on_remove_placement(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        cell = self.table.item(row, 0)
        item_id = cell.data(256) if cell else None
        if item_id is None:
            return
        with self.db.get_session() as session:
            LCSSRepository(session).dispose_item(item_id)
        self.refresh_table()
