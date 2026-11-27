"""Chemical safety registry & cabinet placement check view with manual editing and multi-column filters."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.chem_resolver import ChemResolver, validate_cas_checksum
from app.core.compatibility import CompatibilityEngine
from app.db.database import DatabaseManager
from app.db.repository import LCSSRepository
from app.schemas import CompatibilityLevel, ControlLevel, GroupSource, ItemStatus, ResolvedChemical
from app.ui.widgets.common import CompatibilityWarningDialog, GHSPictogramStrip, MoleculePreviewWidget
from app.ui.workers import AsyncWorker

GHS_CODES = [f"GHS0{i}" for i in range(1, 10)]


class InventoryView(QWidget):
    """Chemical master resolution / manual editing + cabinet placement compatibility safety check."""

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

        # Left: Registered chemicals & cabinet placement with multi-column filters
        left_panel = QVBoxLayout()
        filter_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜尋品名 / CAS...")
        self.search_input.textChanged.connect(self.refresh_table)

        self.filter_loc_combo = QComboBox()
        self.filter_loc_combo.currentIndexChanged.connect(self.refresh_table)

        self.filter_signal_combo = QComboBox()
        self.filter_signal_combo.addItem("全部警示語", "ALL")
        self.filter_signal_combo.addItem("危險", "危險")
        self.filter_signal_combo.addItem("警告", "警告")
        self.filter_signal_combo.addItem("無", "無")
        self.filter_signal_combo.currentIndexChanged.connect(self.refresh_table)

        self.filter_ctrl_combo = QComboBox()
        self.filter_ctrl_combo.addItem("全部管制等級", "ALL")
        for cl in ControlLevel:
            self.filter_ctrl_combo.addItem(cl.value, cl.value)
        self.filter_ctrl_combo.currentIndexChanged.connect(self.refresh_table)

        filter_row.addWidget(self.search_input, 2)
        filter_row.addWidget(self.filter_loc_combo, 2)
        filter_row.addWidget(self.filter_signal_combo, 1)
        filter_row.addWidget(self.filter_ctrl_combo, 1)
        left_panel.addLayout(filter_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["中文品名", "英文品名", "CAS No.", "警示語", "管制等級", "配置櫃位"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._on_table_row_selected)
        left_panel.addWidget(self.table)

        action_row = QHBoxLayout()
        remove_btn = QPushButton("從櫃位移除選取紀錄")
        remove_btn.clicked.connect(self._on_remove_placement)
        clear_form_btn = QPushButton("清空右側表單 (手動新增)")
        clear_form_btn.clicked.connect(self._clear_form)
        action_row.addWidget(remove_btn)
        action_row.addWidget(clear_form_btn)
        action_row.addStretch(1)
        left_panel.addLayout(action_row)
        main_layout.addLayout(left_panel, 3)

        # Right: Chemical resolution + editable manual fields + cabinet safety placement check
        right_box = QGroupBox("藥品解析／手動編輯與櫃位安全檢查")
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_inner = QWidget()
        right_layout = QVBoxLayout(right_inner)

        cas_row = QHBoxLayout()
        self.cas_input = QLineEdit()
        self.cas_input.setPlaceholderText("輸入 CAS（例：7647-01-0）或英文品名")
        self.resolve_btn = QPushButton("線上／離線解析")
        self.resolve_btn.clicked.connect(self._on_resolve)
        cas_row.addWidget(self.cas_input)
        cas_row.addWidget(self.resolve_btn)
        right_layout.addLayout(cas_row)

        self.resolved_lbl = QLabel("可直接手動輸入下方欄位，或輸入 CAS/品名自動解析帶入。")
        self.resolved_lbl.setWordWrap(True)
        right_layout.addWidget(self.resolved_lbl)

        edit_form = QFormLayout()
        self.edit_cas = QLineEdit()
        self.edit_name_zh = QLineEdit()
        self.edit_name_en = QLineEdit()
        self.edit_formula = QLineEdit()
        self.edit_smiles = QLineEdit()
        self.edit_smiles.editingFinished.connect(self._on_smiles_edited)
        self.edit_signal = QComboBox()
        self.edit_signal.addItems(["無", "危險", "警告"])
        self.edit_control = QComboBox()
        for cl in ControlLevel:
            self.edit_control.addItem(cl.value, cl.value)
        self.location_combo = QComboBox()

        edit_form.addRow("CAS No.*：", self.edit_cas)
        edit_form.addRow("中文品名：", self.edit_name_zh)
        edit_form.addRow("英文品名：", self.edit_name_en)
        edit_form.addRow("分子式：", self.edit_formula)
        edit_form.addRow("SMILES：", self.edit_smiles)
        edit_form.addRow("警示語：", self.edit_signal)
        edit_form.addRow("管制等級：", self.edit_control)
        edit_form.addRow("目標存放櫃位：", self.location_combo)
        right_layout.addLayout(edit_form)

        right_layout.addWidget(QLabel("GHS 危害圖示勾選："))
        ghs_grid = QHBoxLayout()
        self.ghs_checks: dict[str, QCheckBox] = {}
        for code in GHS_CODES:
            chk = QCheckBox(code.replace("GHS", ""))
            chk.setToolTip(code)
            chk.toggled.connect(self._on_ghs_checks_changed)
            self.ghs_checks[code] = chk
            ghs_grid.addWidget(chk)
        right_layout.addLayout(ghs_grid)

        self.ghs_strip = GHSPictogramStrip()
        right_layout.addWidget(self.ghs_strip)

        self.mol_preview = MoleculePreviewWidget()
        right_layout.addWidget(self.mol_preview)

        btn_row = QHBoxLayout()
        save_master_btn = QPushButton("僅儲存藥品修改")
        save_master_btn.clicked.connect(self._on_save_chemical_only)
        self.checkin_btn = QPushButton("檢查相容性並登錄櫃位")
        self.checkin_btn.setStyleSheet("background: #1e3a8a; color: #fff; font-weight: bold; padding: 8px;")
        self.checkin_btn.clicked.connect(self._on_register_placement)
        btn_row.addWidget(save_master_btn)
        btn_row.addWidget(self.checkin_btn)
        right_layout.addLayout(btn_row)
        right_layout.addStretch(1)

        right_scroll.setWidget(right_inner)
        outer_right = QVBoxLayout(right_box)
        outer_right.addWidget(right_scroll)
        main_layout.addWidget(right_box, 2)

        self.reload_locations()
        self.refresh_table()

    def reload_locations(self) -> None:
        prev_target = self.location_combo.currentData()
        prev_filter = self.filter_loc_combo.currentData()

        self.location_combo.clear()
        self.filter_loc_combo.blockSignals(True)
        self.filter_loc_combo.clear()
        self.filter_loc_combo.addItem("全部櫃位", "ALL")
        self.filter_loc_combo.addItem("未指定櫃位", "UNASSIGNED")

        with self.db.get_session() as session:
            for loc in LCSSRepository(session).list_locations():
                label = f"{loc.display_name} [{loc.cabinet_type}]"
                self.location_combo.addItem(label, loc.id)
                self.filter_loc_combo.addItem(loc.display_name, loc.id)

        if prev_target is not None:
            idx = self.location_combo.findData(prev_target)
            if idx >= 0:
                self.location_combo.setCurrentIndex(idx)
        if prev_filter is not None:
            idx = self.filter_loc_combo.findData(prev_filter)
            if idx >= 0:
                self.filter_loc_combo.setCurrentIndex(idx)
        self.filter_loc_combo.blockSignals(False)

    def refresh_table(self) -> None:
        query = self.search_input.text().strip()
        loc_filter = self.filter_loc_combo.currentData()
        sig_filter = self.filter_signal_combo.currentData()
        ctrl_filter = self.filter_ctrl_combo.currentData()

        with self.db.get_session() as session:
            items = LCSSRepository(session).list_inventory_items(
                search=query, status=ItemStatus.IN_STOCK.value
            )

        filtered = []
        for it in items:
            if loc_filter == "UNASSIGNED" and it.location_id is not None:
                continue
            if isinstance(loc_filter, int) and it.location_id != loc_filter:
                continue
            sig_val = (it.chemical.signal_word or "無") if it.chemical else "無"
            if sig_filter and sig_filter != "ALL" and sig_val != sig_filter:
                continue
            ctrl_val = it.chemical.control_level if it.chemical else "NORMAL"
            if ctrl_filter and ctrl_filter != "ALL" and ctrl_val != ctrl_filter:
                continue
            filtered.append(it)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(filtered))
        for r, it in enumerate(filtered):
            name_zh = it.chemical.name_zh if it.chemical else ""
            name_en = it.chemical.name_en if it.chemical else ""
            cas = it.chemical.cas_number if it.chemical else ""
            signal = (it.chemical.signal_word or "無") if it.chemical else "無"
            ctrl = it.chemical.control_level if it.chemical else "NORMAL"
            loc = it.location.display_name if it.location else "未指定櫃位"
            for c, v in enumerate([name_zh, name_en, cas, signal, ctrl, loc]):
                cell = QTableWidgetItem(v)
                cell.setData(Qt.ItemDataRole.UserRole, it.id)
                cell.setData(Qt.ItemDataRole.UserRole + 1, it.chemical_id)
                self.table.setItem(r, c, cell)
        self.table.setSortingEnabled(True)

    def _clear_form(self) -> None:
        self._current_resolved = None
        self.edit_cas.clear()
        self.edit_name_zh.clear()
        self.edit_name_en.clear()
        self.edit_formula.clear()
        self.edit_smiles.clear()
        self.edit_signal.setCurrentText("無")
        self.edit_control.setCurrentText(ControlLevel.NORMAL.value)
        for chk in self.ghs_checks.values():
            chk.blockSignals(True)
            chk.setChecked(False)
            chk.blockSignals(False)
        self.ghs_strip.set_pictograms([])
        self.mol_preview.set_smiles("")
        self.resolved_lbl.setText("手動新增模式：請填寫 CAS 與藥品資訊。")

    def _on_table_row_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        cell = self.table.item(row, 0)
        if not cell:
            return
        chem_id = cell.data(Qt.ItemDataRole.UserRole + 1)
        if not chem_id:
            return
        with self.db.get_session() as session:
            chem = LCSSRepository(session).get_chemical_by_id(chem_id)
            if chem is None:
                return
            resolved = ResolvedChemical(
                cas_number=chem.cas_number,
                name_zh=chem.name_zh,
                name_en=chem.name_en,
                formula=chem.formula,
                molecular_weight=chem.molecular_weight,
                smiles=chem.smiles,
                inchikey=chem.inchikey,
                ghs_pictograms=chem.ghs_pictograms,
                signal_word=chem.signal_word,
                h_codes=chem.h_codes,
                p_codes=chem.p_codes,
                reactive_groups=chem.reactive_groups,
                group_source=GroupSource(chem.group_source),
                control_level=ControlLevel(chem.control_level),
                data_source=chem.data_source,
            )
        self._populate_editor(resolved)

    def _populate_editor(self, result: ResolvedChemical) -> None:
        self._current_resolved = result
        self.edit_cas.setText(result.cas_number)
        self.edit_name_zh.setText(result.name_zh)
        self.edit_name_en.setText(result.name_en)
        self.edit_formula.setText(result.formula)
        self.edit_smiles.setText(result.smiles)
        self.edit_signal.setCurrentText(result.signal_word or "無")
        idx_ctrl = self.edit_control.findData(result.control_level.value)
        if idx_ctrl >= 0:
            self.edit_control.setCurrentIndex(idx_ctrl)
        for code, chk in self.ghs_checks.items():
            chk.blockSignals(True)
            chk.setChecked(code in result.ghs_pictograms)
            chk.blockSignals(False)
        self.ghs_strip.set_pictograms(result.ghs_pictograms)
        self.mol_preview.set_smiles(result.smiles)
        self.resolved_lbl.setText(
            f"已載入：<b>{result.name_zh or result.name_en}</b> ({result.cas_number}) ｜ 來源：{result.data_source}"
        )

    def _on_smiles_edited(self) -> None:
        self.mol_preview.set_smiles(self.edit_smiles.text())

    def _on_ghs_checks_changed(self) -> None:
        selected = [code for code, chk in self.ghs_checks.items() if chk.isChecked()]
        self.ghs_strip.set_pictograms(selected)

    def _collect_edited_chemical(self) -> Optional[ResolvedChemical]:
        cas = self.edit_cas.text().strip()
        if not cas:
            QMessageBox.warning(self, "欄位缺漏", "請輸入 CAS No.。")
            return None
        name_zh = self.edit_name_zh.text().strip()
        name_en = self.edit_name_en.text().strip()
        if not name_zh and not name_en:
            QMessageBox.warning(self, "欄位缺漏", "請至少輸入中文或英文品名。")
            return None
        signal = self.edit_signal.currentText()
        picts = [code for code, chk in self.ghs_checks.items() if chk.isChecked()]
        ctrl = ControlLevel(self.edit_control.currentData() or ControlLevel.NORMAL.value)
        smiles = self.edit_smiles.text().strip()

        base = self._current_resolved
        groups, grp_src, _ = self.compat_engine.classify_reactive_groups(
            cas, smiles, base.reactive_groups if base else None
        )
        return ResolvedChemical(
            cas_number=cas,
            name_zh=name_zh,
            name_en=name_en,
            formula=self.edit_formula.text().strip(),
            molecular_weight=base.molecular_weight if base else None,
            smiles=smiles,
            inchikey=base.inchikey if base else "",
            ghs_pictograms=picts,
            signal_word=None if signal == "無" else signal,
            h_codes=base.h_codes if base else [],
            p_codes=base.p_codes if base else [],
            reactive_groups=groups,
            group_source=grp_src,
            control_level=ctrl,
            sds_payload=base.sds_payload if base else None,
            data_source=base.data_source if base else "MANUAL_INPUT",
        )

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
                            control_level=ControlLevel(cached.control_level),
                            data_source="LOCAL_SQLITE_CACHE",
                        )
            return self.resolver.resolve_online(q)

        worker = AsyncWorker(_task)
        worker.signals.finished.connect(self._on_resolved_done)
        worker.signals.error.connect(self._on_resolved_error)
        self.thread_pool.start(worker)

    def _on_resolved_done(self, result: Optional[ResolvedChemical]) -> None:
        self.resolve_btn.setEnabled(True)
        if result is None:
            self.resolved_lbl.setText("查無此藥品資料，您可直接在下方手動輸入建檔。")
            return
        self._populate_editor(result)

    def _on_resolved_error(self, err: str) -> None:
        self.resolve_btn.setEnabled(True)
        self.resolved_lbl.setText(f"解析發生錯誤：{err.splitlines()[0]}")

    def _on_save_chemical_only(self) -> None:
        edited = self._collect_edited_chemical()
        if edited is None:
            return
        with self.db.get_session() as session:
            LCSSRepository(session).upsert_chemical(edited)
        self.refresh_table()
        QMessageBox.information(self, "儲存成功", f"已儲存 {edited.name_zh or edited.name_en} ({edited.cas_number})。")

    def _on_register_placement(self) -> None:
        edited = self._collect_edited_chemical()
        if edited is None:
            return
        loc_id = self.location_combo.currentData()
        override_reason = ""

        with self.db.get_session() as session:
            repo = LCSSRepository(session)
            chem = repo.upsert_chemical(edited)

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
                    if ex.chemical and ex.chemical_id != chem.id:
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
        item_id = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if item_id is None:
            return
        with self.db.get_session() as session:
            LCSSRepository(session).dispose_item(item_id)
        self.refresh_table()
