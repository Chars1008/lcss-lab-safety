"""Reusable PySide6 widgets: GHS pictograms, RDKit 2D structure preview, and warning dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem
from rdkit.Chem import Draw

from app.config import DATA_DIR
from app.schemas import CompatibilityIssue, CompatibilityLevel


class GHSPictogramStrip(QWidget):
    """Displays GHS01-GHS09 SVG pictograms horizontally."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._empty_label = QLabel("無 GHS 危害圖示")
        self._empty_label.setStyleSheet("color: #6b7280;")
        self._layout.addWidget(self._empty_label)

    def set_pictograms(self, codes: list[str], data_dir: Optional[Path] = None) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        base = (data_dir or DATA_DIR) / "ghs_pictograms"
        added = 0
        for code in codes:
            svg_path = base / f"{code}.svg"
            if svg_path.exists():
                svg = QSvgWidget(str(svg_path))
                svg.setFixedSize(44, 44)
                svg.setToolTip(code)
                self._layout.addWidget(svg)
                added += 1

        if added == 0:
            lbl = QLabel("無危害圖示")
            lbl.setStyleSheet("color: #6b7280;")
            self._layout.addWidget(lbl)
        self._layout.addStretch(1)


class MoleculePreviewWidget(QLabel):
    """Renders 2D molecular structure from SMILES using RDKit."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(180, 140)
        self.setStyleSheet("border: 1px solid #d1d5db; background: #ffffff; border-radius: 6px;")
        self.setText("無結構預覽")

    def set_smiles(self, smiles: str) -> None:
        if not smiles.strip():
            self.setPixmap(QPixmap())
            self.setText("無 SMILES 資料")
            return
        mol = Chem.MolFromSmiles(smiles.strip())
        if mol is None:
            self.setPixmap(QPixmap())
            self.setText("SMILES 解析失敗")
            return
        pil_img = Draw.MolToImage(mol, size=(220, 160)).convert("RGBA")
        data = pil_img.tobytes("raw", "RGBA")
        qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888)
        self.setPixmap(QPixmap.fromImage(qimg))


class CompatibilityWarningDialog(QDialog):
    """Mandatory warning dialog when check-in/move triggers INCOMPATIBLE or CAUTION."""

    def __init__(
        self,
        issues: list[CompatibilityIssue],
        cabinet_warning: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("藥品相容性安全警告")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        title = QLabel("⚠️ 偵測到存放相容性風險，請確認是否覆寫警告")
        title.setStyleSheet("font-size: 13pt; font-weight: bold; color: #b91c1c;")
        layout.addWidget(title)

        if cabinet_warning:
            cab_lbl = QLabel(cabinet_warning)
            cab_lbl.setWordWrap(True)
            cab_lbl.setStyleSheet(
                "background: #fef2f2; border: 1px solid #ef4444; padding: 8px; border-radius: 4px;"
            )
            layout.addWidget(cab_lbl)

        for issue in issues:
            color = "#dc2626" if issue.level == CompatibilityLevel.INCOMPATIBLE else "#d97706"
            box = QLabel(
                f"<b>[{issue.level.value}] {issue.chem_a_name} × {issue.chem_b_name}</b><br>"
                f"{issue.summary_zh}<br><i>建議：{issue.recommendation_zh}</i>"
            )
            box.setWordWrap(True)
            box.setStyleSheet(f"border-left: 4px solid {color}; padding: 6px 10px; background: #fffbeb;")
            layout.addWidget(box)

        layout.addWidget(QLabel("若因特殊原因仍須強制入庫／移櫃，請填寫管理員覆寫理由（將留存稽核日誌）："))
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("例如：已使用獨立二次防漏托盤隔離存放")
        layout.addWidget(self.reason_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("強制覆寫並寫入")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消操作")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.reason_edit.text().strip():
            self.reason_edit.setFocus()
            self.reason_edit.setStyleSheet("border: 1.5px solid #dc2626;")
            return
        self.accept()

    @property
    def override_reason(self) -> str:
        return self.reason_edit.text().strip()
