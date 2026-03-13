"""
config.py — Pydantic Settings cho Z-ARMOR Backend
"""

from pydantic_settings import BaseSettings
from typing import List
import json


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────
    DEBUG: bool = False

    # ── CORS ─────────────────────────────────────────────────────
    ALLOWED_ORIGINS: List[str] = ["*"]

    # ── Database ─────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+psycopg2://zarmor:Zarmor%402025@127.0.0.1:5432/zarmor_db"

    # ── SMTP Gmail ───────────────────────────────────────────────
    SMTP_USER:         str = ""
    SMTP_APP_PASSWORD: str = ""
    SMTP_FROM_NAME:    str = "Z-ARMOR CLOUD"

    # ── Lark Base ────────────────────────────────────────────────
    LARK_APP_ID:          str = ""
    LARK_APP_SECRET:      str = ""
    LARK_BASE_APP_TOKEN:  str = ""
    LARK_ORDERS_TABLE_ID: str = ""

    # ── Auth / JWT ───────────────────────────────────────────────
    JWT_SECRET_KEY:              str = ""   # WAJIB set: openssl rand -hex 32
    JWT_ACCESS_EXPIRE_MINUTES:   int = 60   # 1 hour
    JWT_REFRESH_EXPIRE_DAYS:     int = 30   # 30 days
    COOKIE_SECURE:               bool = False  # True sau khi có SSL

    # ── Admin ────────────────────────────────────────────────────
    ADMIN_SECRET_KEY: str = "CHANGE_ME"

    # ── Trial config ─────────────────────────────────────────────
    TRIAL_DURATION_DAYS:  int = 7
    TRIAL_MAX_PER_EMAIL:  int = 1

    # ── Telegram notifications ───────────────────────────────────
    TELEGRAM_BOT_TOKEN:      str = ""
    TELEGRAM_ADMIN_CHAT_ID:  str = ""

    # ── Backward compat (tên cũ nếu có trong .env) ───────────────
    ADMIN_TELEGRAM_CHAT_ID:  str = ""

    class Config:
        env_file        = ".env"
        env_file_encoding = "utf-8"
        extra           = "ignore"   # ← đổi từ "ignore" → "ignore" để không crash khi .env có field lạ


settings = Settings()

# Fallback: nếu dùng tên cũ ADMIN_TELEGRAM_CHAT_ID thì sync sang tên mới
if not settings.TELEGRAM_ADMIN_CHAT_ID and settings.ADMIN_TELEGRAM_CHAT_ID:
    settings.TELEGRAM_ADMIN_CHAT_ID = settings.ADMIN_TELEGRAM_CHAT_ID