"""Application views package."""

from app.ui.views.compatibility_view import CompatibilityView
from app.ui.views.dashboard_view import DashboardView
from app.ui.views.emergency_view import EmergencyProcessView
from app.ui.views.inventory_view import InventoryView
from app.ui.views.sds_view import SDSView
from app.ui.views.settings_view import SettingsView

__all__ = [
    "CompatibilityView",
    "DashboardView",
    "EmergencyProcessView",
    "InventoryView",
    "SDSView",
    "SettingsView",
]
