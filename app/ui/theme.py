"""Live light/dark theme stylesheets and full EN/zh-TW UI localization helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow

LIGHT_QSS = """
QMainWindow, QWidget { background-color: #f8fafc; color: #111827; }
QGroupBox {
    font-weight: bold; border: 1px solid #cbd5e1; border-radius: 6px;
    margin-top: 8px; padding-top: 12px; background-color: #ffffff;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #1e3a8a; }
QLineEdit, QTextEdit, QComboBox, QListWidget, QTableWidget, QSpinBox, QDoubleSpinBox {
    background-color: #ffffff; color: #111827; border: 1px solid #cbd5e1; border-radius: 4px; padding: 3px;
}
QHeaderView::section { background-color: #e2e8f0; color: #111827; padding: 4px; border: 1px solid #cbd5e1; }
QPushButton {
    background-color: #e2e8f0; color: #111827; border: 1px solid #cbd5e1;
    border-radius: 4px; padding: 5px 10px;
}
QPushButton:hover { background-color: #cbd5e1; }
QTabWidget::pane { border: 1px solid #cbd5e1; background: #ffffff; }
QTabBar::tab { background: #e2e8f0; color: #1e293b; padding: 6px 12px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #ffffff; color: #1e3a8a; font-weight: bold; }
"""

DARK_QSS = """
QMainWindow, QWidget { background-color: #0f172a; color: #f1f5f9; }
QGroupBox {
    font-weight: bold; border: 1px solid #334155; border-radius: 6px;
    margin-top: 8px; padding-top: 12px; background-color: #1e293b;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #93c5fd; }
QLineEdit, QTextEdit, QComboBox, QListWidget, QTableWidget, QSpinBox, QDoubleSpinBox {
    background-color: #1e293b; color: #f1f5f9; border: 1px solid #475569; border-radius: 4px; padding: 3px;
}
QHeaderView::section { background-color: #334155; color: #f1f5f9; padding: 4px; border: 1px solid #475569; }
QPushButton {
    background-color: #334155; color: #f1f5f9; border: 1px solid #475569;
    border-radius: 4px; padding: 5px 10px;
}
QPushButton:hover { background-color: #475569; }
QTabWidget::pane { border: 1px solid #334155; background: #1e293b; }
QTabBar::tab { background: #334155; color: #cbd5e1; padding: 6px 12px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #1e293b; color: #93c5fd; font-weight: bold; }
"""

NAV_LABELS = {
    "zh-TW": [
        "📊 安全檢查與指引總覽",
        "🧪 藥品登錄與櫃位檢查",
        "⚗️ 相容性矩陣檢查",
        "📄 SDS 與瓶身標籤",
        "🚨 緊急應變流程",
        "⚙️ 設定",
    ],
    "en": [
        "📊 Safety Overview",
        "🧪 Chemical Registry",
        "⚗️ Compatibility Matrix",
        "📄 SDS & Labels",
        "🚨 Emergency Process",
        "⚙️ Settings",
    ],
}

WINDOW_TITLES = {
    "zh-TW": "勤思實驗室藥品安全管理系統(GLCSS)",
    "en": "GEMS Laboratory Chemical Safety System (GLCSS)",
}


def apply_theme(app: QApplication | None, theme: str) -> None:
    """Apply light or dark stylesheet to QApplication."""
    if app is None:
        return
    app.setStyleSheet(DARK_QSS if theme == "dark" else LIGHT_QSS)


def apply_ui_language(win: "MainWindow", lang: str) -> None:
    """Switch main navigation rail, window title, and all 6 views between zh-TW and en."""
    key = "en" if lang == "en" else "zh-TW"
    win.setWindowTitle(WINDOW_TITLES[key])
    for i, label in enumerate(NAV_LABELS[key]):
        if i < win.nav_list.count():
            win.nav_list.item(i).setText(label)

    # 1. DashboardView
    dv = win.dashboard_view
    if key == "en":
        dv.title_lbl.setText("Safety Overview & Guidance")
        dv.refresh_btn.setText("Refresh")
        dv.card_total.title_lbl.setText("Registered Chemicals")
        dv.card_controlled.title_lbl.setText("Controlled / Prohibited")
        dv.card_locations.title_lbl.setText("Storage Cabinets")
        dv.card_conflicts.title_lbl.setText("Cabinet Conflicts")
        dv.alert_table.setHorizontalHeaderLabels(["Alert Type", "Chemical / Cabinet", "Details", "Recommended Action"])
    else:
        dv.title_lbl.setText("安全檢查與指引總覽")
        dv.refresh_btn.setText("重新整理")
        dv.card_total.title_lbl.setText("已建檔化學品數")
        dv.card_controlled.title_lbl.setText("教師專管 / 禁用藥品")
        dv.card_locations.title_lbl.setText("已設定安全櫃位數")
        dv.card_conflicts.title_lbl.setText("櫃位安全衝突警示")
        dv.alert_table.setHorizontalHeaderLabels(["警示類型", "藥品／櫃位", "詳細說明", "安全指引建議"])

    # 2. InventoryView (Chemical Registry & Cabinet Check)
    iv = win.inventory_view
    if key == "en":
        iv.search_input.setPlaceholderText("Search chemical name / CAS...")
        iv.table.setHorizontalHeaderLabels(["Name (ZH)", "Name (EN)", "CAS No.", "Signal Word", "Control Level", "Cabinet"])
        iv.name_lookup_input.setPlaceholderText("Lookup CAS No. by Chinese/English name...")
        iv.name_lookup_btn.setText("Lookup CAS")
        iv.cas_input.setPlaceholderText("Enter CAS (e.g. 7647-01-0) or English name")
        iv.resolve_btn.setText("Resolve Online/Offline")
        iv.checkin_btn.setText("Check Compatibility & Register")
    else:
        iv.search_input.setPlaceholderText("搜尋品名 / CAS...")
        iv.table.setHorizontalHeaderLabels(["中文品名", "英文品名", "CAS No.", "警示語", "管制等級", "配置櫃位"])
        iv.name_lookup_input.setPlaceholderText("輸入中/英文品名查詢 CAS No.（例：鹽酸、Ethanol）")
        iv.name_lookup_btn.setText("查詢 CAS")
        iv.cas_input.setPlaceholderText("輸入 CAS（例：7647-01-0）或英文品名")
        iv.resolve_btn.setText("線上／離線解析")
        iv.checkin_btn.setText("檢查相容性並登錄櫃位")

    # 3. CompatibilityView
    cv = win.compatibility_view
    if key == "en":
        cv.title_lbl.setText("Chemical Compatibility Check Matrix (N × N)")
        cv.reload_btn.setText("Reload")
        cv.select_all_btn.setText("Select All & Check")
        cv.check_btn.setText("Generate N × N Matrix")
    else:
        cv.title_lbl.setText("化學相容性檢查矩陣（N × N 互動檢查器）")
        cv.reload_btn.setText("重新載入")
        cv.select_all_btn.setText("全選並檢查")
        cv.check_btn.setText("產生 N × N 矩陣")

    # 4. SDSView
    sv = win.sds_view
    if key == "en":
        sv.saved_sds_table.setHorizontalHeaderLabels(["Chemical Name", "CAS No.", "Status / Source", "Supplier PDFs"])
        sv.tabs.setTabText(5, "Live Preview (with GHS)")
    else:
        sv.saved_sds_table.setHorizontalHeaderLabels(["品名", "CAS No.", "狀態 / 來源", "原廠 PDF"])
        sv.tabs.setTabText(5, "即時預覽 (含 GHS 圖示)")

    # 5. EmergencyProcessView
    ev = win.emergency_view
    if key == "en":
        ev.title_lbl.setText("Emergency Process (AI-Assisted SDS Response SOP)")
        ev.select_lbl.setText("Chemical:")
        ev.reload_btn.setText("Reload")
        ev.llm_btn.setText("Generate with Local LLM")
        ev.export_btn.setText("Export Emergency SOP PDF")
        ev.box_spill.setTitle("1. Spill / Release Response")
        ev.box_contact.setTitle("2. Skin & Eye Contact First Aid")
        ev.box_ingest.setTitle("3. Inhalation & Ingestion First Aid")
        ev.box_fire.setTitle("4. Fire & Incompatible Reaction")
    else:
        ev.title_lbl.setText("緊急應變流程 (Emergency Process)")
        ev.select_lbl.setText("選擇化學品：")
        ev.reload_btn.setText("重新載入")
        ev.llm_btn.setText("以 Local LLM 生成應變流程")
        ev.export_btn.setText("匯出應變 SOP PDF")
        ev.box_spill.setTitle("1. 外洩應變流程 (Spill / Release Response)")
        ev.box_contact.setTitle("2. 皮膚與眼睛接觸急救 (Skin & Eye Contact First Aid)")
        ev.box_ingest.setTitle("3. 吸入與誤食急救 (Inhalation & Ingestion First Aid)")
        ev.box_fire.setTitle("4. 火災與不相容反應處置 (Fire & Incompatible Reaction)")

    # 6. SettingsView
    stv = win.settings_view
    if key == "en":
        stv.loc_table.setHorizontalHeaderLabels(["Laboratory", "Cabinet Name", "Shelf", "Cabinet Type"])
    else:
        stv.loc_table.setHorizontalHeaderLabels(["實驗室", "藥品櫃名稱", "層架", "櫃體屬性"])
