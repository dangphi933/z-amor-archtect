"""app/core/database.py — user-service DB setup."""
from shared.libs.database.models import (
    engine, SessionLocal, Base, get_db,
    License, ZAUser, AuditLog, AdminUser,
)

__all__ = ["engine", "SessionLocal", "Base", "get_db", "License", "ZAUser", "AuditLog", "AdminUser"]
