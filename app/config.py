"""Application configuration and persistent settings management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = APP_ROOT / "data"
CONFIG_DIR = APP_ROOT / "config"
STORAGE_DIR = APP_ROOT / "storage"
SDS_FILES_DIR = STORAGE_DIR / "sds_files"
LABELS_DIR = STORAGE_DIR / "labels"
EXPORTS_DIR = STORAGE_DIR / "exports"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


class AppSettings(BaseSettings):
    """Pydantic settings persisted to config/settings.json."""

    model_config = SettingsConfigDict(env_prefix="LCSS_", extra="ignore")

    initialized: bool = False
    lab_name: str = "教學研究實驗室"
    lab_manager: str = ""
    emergency_phone: str = "119 / 校安中心"
    organization: str = ""
    db_path: str = str(STORAGE_DIR / "lcss.db")

    # Alert thresholds
    expiry_warning_days: int = 30
    low_stock_threshold_ratio: float = 0.2

    # Local LLM (Ollama) optional integration
    llm_enabled: bool = False
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_seconds: float = 45.0

    # Network resolver settings
    network_timeout_seconds: float = 15.0

    def ensure_directories(self) -> None:
        """Create required runtime directories if missing."""
        for directory in (CONFIG_DIR, STORAGE_DIR, SDS_FILES_DIR, LABELS_DIR, EXPORTS_DIR):
            directory.mkdir(parents=True, exist_ok=True)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def save(self, path: Optional[Path] = None) -> Path:
        """Persist settings to JSON file."""
        target = path or SETTINGS_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppSettings":
        """Load settings from JSON file or return defaults."""
        target = path or SETTINGS_FILE
        if target.exists():
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                return cls(**raw)
            except (json.JSONDecodeError, ValueError):
                pass
        return cls()
