"""app/core/database.py — auth-service DB setup."""
from shared.libs.database.models import (
    engine, SessionLocal, Base, get_db,
    License, LicenseActivation, atomic_bind_license,
    ZAUser, AuditLog, AdminUser, ConfigAuditTrail,
)

__all__ = [
    "engine", "SessionLocal", "Base", "get_db",
    "License", "LicenseActivation", "atomic_bind_license",
    "ZAUser", "AuditLog", "AdminUser", "ConfigAuditTrail",
]
