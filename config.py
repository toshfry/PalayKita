import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "palaykita-local-secret-key-change-later")
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{INSTANCE_DIR / 'palaykita.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"check_same_thread": False}}

    EXPORT_DIR = BASE_DIR / "exports" / "reports"
    DAILY_REPORT_DIR = EXPORT_DIR / "daily"
    WEEKLY_REPORT_DIR = EXPORT_DIR / "weekly"
    MONTHLY_REPORT_DIR = EXPORT_DIR / "monthly"
    CUSTOM_REPORT_DIR = EXPORT_DIR / "custom"
    COMMERCIAL_REPORT_DIR = EXPORT_DIR / "commercial"

    BACKUP_DIR = BASE_DIR / "backups"
