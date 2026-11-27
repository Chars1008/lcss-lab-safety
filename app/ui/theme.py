"""Live light/dark theme stylesheets and EN/zh-TW UI localization helpers."""

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
        "⚙️ 設定",
    ],
    "en": [
        "📊 Safety Overview",
        "🧪 Chemical Registry",
        "⚗️ Compatibility Matrix",
        "📄 SDS & Labels",
        "⚙️ Settings",
    ],
}

WINDOW_TITLES = {
    "zh-TW": "勤思實驗室藥品安全管理系統(GLCSS)",
    "en": "Ginsi Laboratory Chemical Safety System (GLCSS)",
}


def apply_theme(app: QApplication | None, theme: str) -> None:
    """Apply light or dark stylesheet to QApplication."""
    if app is None:
        return
    app.setStyleSheet(DARK_QSS if theme == "dark" else LIGHT_QSS)


def apply_ui_language(win: "MainWindow", lang: str) -> None:
    """Switch main navigation rail, window title, and key view labels between zh-TW and en."""
    key = "en" if lang == "en" else "zh-TW"
    win.setWindowTitle(WINDOW_TITLES[key])
    for i, label in enumerate(NAV_LABELS[key]):
        if i < win.nav_list.count():
            win.nav_list.item(i).setText(label)

    # Update key view headings/buttons cleanly
    if key == "en":
        win.dashboard_view.refresh_btn.setText("Refresh")
        win.inventory_view.resolve_btn.setText("Resolve Online/Offline")
        win.inventory_view.name_lookup_btn.setText("Lookup CAS")
        win.inventory_view.checkin_btn.setText("Check Compatibility & Register")
        win.sds_view.lang_combo.setToolTip("Select SDS export language")
    else:
        win.dashboard_view.refresh_btn.setText("重新整理")
        win.inventory_view.resolve_btn.setText("線上／離線解析")
        win.inventory_view.name_lookup_btn.setText("查詢 CAS")
        win.inventory_view.checkin_btn.setText("檢查相容性並登錄櫃位")
