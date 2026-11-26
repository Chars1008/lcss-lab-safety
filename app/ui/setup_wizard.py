"""First-run PySide6 QWizard for environment check, lab setup, presets, and optional Ollama."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from app.config import AppSettings
from app.core.chem_resolver import ChemResolver
from app.core.llm_service import LocalLLMService
from app.db.database import DatabaseManager
from app.db.repository import LCSSRepository
from app.schemas import CabinetType


class WelcomeHealthPage(QWizardPage):
    """Page 1: Environment health check."""

    def __init__(self, settings: AppSettings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle("歡迎使用勤思實驗室藥品安全管理系統(GLCSS)")
        self.setSubTitle("步驟 1/4：執行環境與核心元件健康檢查")

        try:
            from rdkit import __version__ as rdkit_ver
            rdkit_status = f"✅ 正常 ({rdkit_ver})"
        except Exception:
            rdkit_status = "❌ 無法載入"

        layout = QVBoxLayout(self)
        info = QLabel(
            f"<b>Python 版本：</b> {sys.version.split()[0]}<br>"
            f"<b>執行環境路徑：</b> {sys.prefix}<br>"
            f"<b>RDKit 化學引擎：</b> {rdkit_status}<br>"
            f"<b>SQLite 資料庫路徑：</b> {settings.db_path}"
        )
        info.setWordWrap(True)
        layout.addWidget(info)


class LabInfoPage(QWizardPage):
    """Page 2: Lab name, manager, and emergency phone (used in SDS Section 1)."""

    def __init__(self, settings: AppSettings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle("實驗室基本資訊與緊急聯絡網")
        self.setSubTitle("步驟 2/4：此資訊將自動帶入系統生成之 SDS 第 1 節")

        form = QFormLayout(self)
        self.lab_name_edit = QLineEdit(settings.lab_name)
        self.manager_edit = QLineEdit(settings.lab_manager)
        self.phone_edit = QLineEdit(settings.emergency_phone)
        form.addRow("實驗室名稱：", self.lab_name_edit)
        form.addRow("管理負責人：", self.manager_edit)
        form.addRow("校安／緊急聯絡電話：", self.phone_edit)


class CabinetPresetPage(QWizardPage):
    """Page 3: Pre-create standard cabinets and optional demo reagents."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle("初始化藥品櫃與示範資料")
        self.setSubTitle("步驟 3/4：勾選欲自動建立的標準藥品櫃範本")

        layout = QVBoxLayout(self)
        self.chk_flammable = QCheckBox("防火易燃櫃（存放乙醇、丙酮等有機溶劑）")
        self.chk_corrosive = QCheckBox("耐酸鹼腐蝕櫃（存放鹽酸、硫酸、氫氧化鈉等）")
        self.chk_general = QCheckBox("一般常溫藥品櫃（存放中性鹽類、緩衝液）")
        self.chk_fridge = QCheckBox("4°C 試劑冰箱（存放生物試劑與低溫藥品）")
        self.chk_demo = QCheckBox("匯入常見教學實驗室示範藥品（鹽酸、乙醇、漂白水等）")

        for chk in (
            self.chk_flammable,
            self.chk_corrosive,
            self.chk_general,
            self.chk_fridge,
            self.chk_demo,
        ):
            chk.setChecked(True)
            layout.addWidget(chk)


class OllamaSetupPage(QWizardPage):
    """Page 4: Optional Ollama detection with prominent offline-mode skip."""

    def __init__(self, settings: AppSettings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setTitle("Local LLM（Ollama）選配設定")
        self.setSubTitle("步驟 4/4：本軟體核心功能 100% 支援純離線規則模式，Ollama 僅作為翻譯與 PDF 萃取輔助")

        layout = QVBoxLayout(self)
        self.status_lbl = QLabel("點擊下方按鈕偵測本機 Ollama (http://localhost:11434)，或直接略過。")
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        self.detect_btn = QPushButton("偵測本機 Ollama")
        self.detect_btn.clicked.connect(self._detect)
        layout.addWidget(self.detect_btn)

        self.enable_chk = QCheckBox("啟用 Ollama 輔助功能")
        self.enable_chk.setChecked(False)
        layout.addWidget(self.enable_chk)

        skip_btn = QPushButton("略過，先以純離線規則模式使用")
        skip_btn.setStyleSheet("background: #0f766e; color: #fff; font-weight: bold; padding: 6px;")
        skip_btn.clicked.connect(self._skip)
        layout.addWidget(skip_btn)

    def _detect(self) -> None:
        svc = LocalLLMService(host=self.settings.ollama_host)
        ok, models = svc.check_connection()
        if ok:
            self.status_lbl.setText(f"✅ 已偵測到 Ollama！可用模型：{', '.join(models) or '無'}")
            self.enable_chk.setChecked(True)
        else:
            self.status_lbl.setText("⚠️ 未偵測到執行中的 Ollama（可至 ollama.com 下載，或直接略過使用純離線模式）。")
            self.enable_chk.setChecked(False)

    def _skip(self) -> None:
        self.enable_chk.setChecked(False)
        if self.wizard():
            self.wizard().accept()


class SetupWizard(QWizard):
    """First-run configuration wizard."""

    def __init__(
        self,
        db: DatabaseManager,
        settings: AppSettings,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.setWindowTitle("GLCSS 首次啟動設定精靈")
        self.resize(620, 440)

        self.page_welcome = WelcomeHealthPage(settings)
        self.page_lab = LabInfoPage(settings)
        self.page_cabinets = CabinetPresetPage()
        self.page_ollama = OllamaSetupPage(settings)

        self.addPage(self.page_welcome)
        self.addPage(self.page_lab)
        self.addPage(self.page_cabinets)
        self.addPage(self.page_ollama)

        self.accepted.connect(self._apply_setup)

    def _apply_setup(self) -> None:
        self.settings.lab_name = self.page_lab.lab_name_edit.text().strip() or "教學研究實驗室"
        self.settings.lab_manager = self.page_lab.manager_edit.text().strip()
        self.settings.emergency_phone = self.page_lab.phone_edit.text().strip() or "119 / 校安中心"
        self.settings.llm_enabled = self.page_ollama.enable_chk.isChecked()
        self.settings.initialized = True
        self.settings.save()

        with self.db.get_session() as session:
            repo = LCSSRepository(session)
            lab = self.settings.lab_name
            loc_map: dict[str, int] = {}

            presets = [
                (self.page_cabinets.chk_flammable.isChecked(), "防火易燃櫃", CabinetType.FLAMMABLE.value),
                (self.page_cabinets.chk_corrosive.isChecked(), "耐酸鹼腐蝕櫃", CabinetType.CORROSIVE.value),
                (self.page_cabinets.chk_general.isChecked(), "一般常溫藥品櫃", CabinetType.GENERAL.value),
                (self.page_cabinets.chk_fridge.isChecked(), "4°C 試劑冰箱", CabinetType.FRIDGE_4C.value),
            ]
            for enabled, cname, ctype in presets:
                if enabled:
                    loc = repo.create_location(lab, cname, "第 1 層", ctype)
                    loc_map[ctype] = loc.id

            if self.page_cabinets.chk_demo.isChecked():
                resolver = ChemResolver()
                demos = [
                    ("7647-01-0", CabinetType.CORROSIVE.value, 500.0),
                    ("64-17-5", CabinetType.FLAMMABLE.value, 1000.0),
                    ("7681-52-9", CabinetType.GENERAL.value, 500.0),
                ]
                for cas, target_type, cap in demos:
                    resolved = resolver.resolve_offline(cas)
                    if resolved:
                        chem = repo.upsert_chemical(resolved)
                        loc_id = loc_map.get(target_type)
                        repo.check_in_item(
                            chemical_id=chem.id,
                            location_id=loc_id,
                            capacity=cap,
                            unit="mL",
                            brand="示範藥品",
                            expiry_date=date.today() + timedelta(days=365),
                        )
