"""Inventory management view: search, barcode scan, check-in with compatibility guard, check-out."""

from __future__ import annotations

from datetime import date
from typing import Optional

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
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
from app.schemas import CompatibilityLevel, ItemStatus, ItemType, ResolvedChemical
from app.ui.widgets.common import CompatibilityWarningDialog, GHSPictogramStrip, MoleculePreviewWidget
from app.ui.workers import AsyncWorker


class InventoryView(QWidget):
    """Chemical master resolution + physical inventory check-in / check-out / dispose."""

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

        # Left: Inventory list & quick barcode search
        left_panel = QVBoxLayout()
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("掃描條碼或搜尋品名 / CAS...")
        self.search_input.returnPressed.connect(self.refresh_table)
        search_btn = QPushButton("搜尋")
        search_btn.clicked.connect(self.refresh_table)
        search_row.addWidget(self.search_input)
        search_row.addWidget(search_btn)
        left_panel.addLayout(search_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["條碼", "品名", "CAS", "類型", "剩餘量", "存放位置"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        left_panel.addWidget(self.table)

        action_row = QHBoxLayout()
        self.checkout_qty = QDoubleSpinBox()
        self.checkout_qty.setRange(0.1, 100000.0)
        self.checkout_qty.setValue(10.0)
        checkout_btn = QPushButton("領用扣量")
        checkout_btn.clicked.connect(self._on_checkout)
        dispose_btn = QPushButton("標記報廢")
        dispose_btn.clicked.connect(self._on_dispose)
        action_row.addWidget(QLabel("領用量："))
        action_row.addWidget(self.checkout_qty)
        action_row.addWidget(checkout_btn)
        action_row.addWidget(dispose_btn)
        action_row.addStretch(1)
        left_panel.addLayout(action_row)
        main_layout.addLayout(left_panel, 3)

        # Right: Resolve & Check-in form
        right_box = QGroupBox("藥品解析與入庫（含相容性防呆）")
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
        self.item_type_combo = QComboBox()
        self.item_type_combo.addItem("原裝試劑", ItemType.COMMERCIAL.value)
        self.item_type_combo.addItem("自配 / 分裝試劑", ItemType.PREPARED.value)

        self.location_combo = QComboBox()
        self.capacity_spin = QDoubleSpinBox()
        self.capacity_spin.setRange(0.1, 100000.0)
        self.capacity_spin.setValue(500.0)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["mL", "L", "g", "kg", "瓶"])
        self.brand_edit = QLineEdit()
        self.concentration_edit = QLineEdit()
        self.prepared_by_edit = QLineEdit()
        self.expiry_edit = QDateEdit()
        self.expiry_edit.setCalendarPopup(True)
        self.expiry_edit.setDate(date.today().replace(year=date.today().year + 1))

        form.addRow("試劑類型：", self.item_type_combo)
        form.addRow("目標位置：", self.location_combo)
        form.addRow("容量：", self.capacity_spin)
        form.addRow("單位：", self.unit_combo)
        form.addRow("廠牌 / 批號：", self.brand_edit)
        form.addRow("濃度 (自配選填)：", self.concentration_edit)
        form.addRow("配製者 (自配選填)：", self.prepared_by_edit)
        form.addRow("有效期限：", self.expiry_edit)
        right_layout.addLayout(form)

        self.checkin_btn = QPushButton("檢查相容性並入庫")
        self.checkin_btn.setStyleSheet("background: #1e3a8a; color: #fff; font-weight: bold; padding: 8px;")
        self.checkin_btn.clicked.connect(self._on_checkin)
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
            items = LCSSRepository(session).list_inventory_items(search=query, status=ItemStatus.IN_STOCK.value)
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            name = (it.chemical.name_zh or it.chemical.name_en) if it.chemical else ""
            cas = it.chemical.cas_number if it.chemical else ""
            loc = it.location.display_name if it.location else "未指定"
            vals = [
                it.barcode,
                name,
                cas,
                "自配" if it.item_type == ItemType.PREPARED.value else "原裝",
                f"{it.current_quantity:g} / {it.capacity:g} {it.unit}",
                loc,
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                cell.setData(256, it.id)
                self.table.setItem(r, c, cell)

    def _on_resolve(self) -> None:
        q = self.cas_input.text().strip()
        if not q:
            return
        self.resolve_btn.setEnabled(False)
        self.resolved_lbl.setText("正在背景查詢藥品資料...")

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

    def _on_checkin(self) -> None:
        if self._current_resolved is None:
            QMessageBox.warning(self, "提醒", "請先解析藥品資料再進行入庫。")
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
                capacity=self.capacity_spin.value(),
                unit=self.unit_combo.currentText(),
                item_type=self.item_type_combo.currentData(),
                brand=self.brand_edit.text().strip(),
                concentration=self.concentration_edit.text().strip(),
                prepared_by=self.prepared_by_edit.text().strip(),
                expiry_date=self.expiry_edit.date().toPython(),
                override_warning_reason=override_reason,
            )

        self.refresh_table()
        QMessageBox.information(self, "入庫成功", "藥品已成功寫入庫存並記錄稽核日誌。")

    def _selected_item_id(self) -> Optional[int]:
        row = self.table.currentRow()
        if row < 0:
            return None
        cell = self.table.item(row, 0)
        return cell.data(256) if cell else None

    def _on_checkout(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        with self.db.get_session() as session:
            LCSSRepository(session).check_out_quantity(item_id, self.checkout_qty.value())
        self.refresh_table()

    def _on_dispose(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        with self.db.get_session() as session:
            LCSSRepository(session).dispose_item(item_id)
        self.refresh_table()
