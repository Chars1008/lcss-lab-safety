"""Main desktop window with left navigation rail and 5 functional tabs."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from app.config import AppSettings
from app.core.chem_resolver import ChemResolver
from app.core.compatibility import CompatibilityEngine
from app.core.llm_service import LocalLLMService
from app.core.pdf_parser import PDFParser
from app.core.sds_generator import SDSGenerator
from app.db.database import DatabaseManager
from app.ui.views import (
    CompatibilityView,
    DashboardView,
    InventoryView,
    SDSView,
    SettingsView,
)


class MainWindow(QMainWindow):
    """Primary PySide6 application window for LCSS."""

    def __init__(
        self,
        db: DatabaseManager,
        settings: AppSettings,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.setWindowTitle("勤思實驗室藥品安全管理系統(GLCSS)")
        self.resize(1180, 760)

        self.resolver = ChemResolver(timeout=settings.network_timeout_seconds)
        self.compat_engine = CompatibilityEngine()
        self.sds_gen = SDSGenerator()
        self.pdf_parser = PDFParser()
        self.llm_service = LocalLLMService(
            host=settings.ollama_host,
            model=settings.ollama_model,
            enabled=settings.llm_enabled,
            timeout=settings.ollama_timeout_seconds,
        )

        central = QWidget()
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(185)
        self.nav_list.setStyleSheet(
            "QListWidget { background: #1e293b; color: #f8fafc; font-size: 11pt; border: none; padding-top: 10px; }"
            "QListWidget::item { padding: 12px 14px; }"
            "QListWidget::item:selected { background: #2563eb; font-weight: bold; }"
        )
        self.nav_list.addItems([
            "📊 安全檢查與指引總覽",
            "🧪 藥品登錄與櫃位檢查",
            "⚗️ 相容性矩陣檢查",
            "📄 SDS 與瓶身標籤",
            "⚙️ 系統與 Ollama 設定",
        ])

        self.stack = QStackedWidget()
        self.dashboard_view = DashboardView(self.db, self.settings, self.compat_engine)
        self.inventory_view = InventoryView(self.db, self.resolver, self.compat_engine)
        self.compatibility_view = CompatibilityView(self.db, self.compat_engine)
        self.sds_view = SDSView(
            self.db, self.settings, self.resolver, self.sds_gen, self.pdf_parser, self.llm_service
        )
        self.settings_view = SettingsView(
            self.db,
            self.settings,
            self.llm_service,
            on_locations_changed=self.inventory_view.reload_locations,
            on_data_imported=self._refresh_all_views,
        )

        for view in (
            self.dashboard_view,
            self.inventory_view,
            self.compatibility_view,
            self.sds_view,
            self.settings_view,
        ):
            self.stack.addWidget(view)

        self.nav_list.currentRowChanged.connect(self._on_tab_changed)
        self.nav_list.setCurrentRow(0)

        root_layout.addWidget(self.nav_list)
        root_layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

    def _refresh_all_views(self) -> None:
        self.dashboard_view.refresh()
        self.inventory_view.reload_locations()
        self.inventory_view.refresh_table()
        self.compatibility_view.reload_chemicals()
        self.sds_view.reload_chemicals()

    def _on_tab_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.dashboard_view.refresh()
        elif index == 1:
            self.inventory_view.reload_locations()
            self.inventory_view.refresh_table()
        elif index == 2:
            self.compatibility_view.reload_chemicals()
        elif index == 3:
            self.sds_view.reload_chemicals()
        elif index == 4:
            self.settings_view.reload_locations_table()
