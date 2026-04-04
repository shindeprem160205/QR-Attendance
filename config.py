"""
Application configuration loaded from environment variables.

Render provides DATABASE_URL for PostgreSQL. Locally, omit it to use SQLite.
"""
import os
from datetime import timedelta

# Project root (folder containing this file) — used for a reliable SQLite path on all OSes
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _normalize_database_url(url: str) -> str:
    """Render historically used postgres://; SQLAlchemy 2.x expects postgresql://."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    """Base config — override via environment variables."""

    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-in-production"

    # SQLite fallback: absolute path so the DB opens no matter which directory you run Flask from
    _db_url = os.environ.get("DATABASE_URL")
    if _db_url:
        SQLALCHEMY_DATABASE_URI = _normalize_database_url(_db_url)
    else:
        _instance_dir = os.path.join(BASE_DIR, "instance")
        os.makedirs(_instance_dir, exist_ok=True)
        _sqlite_file = os.path.join(_instance_dir, "attendance.db")
        # Windows paths need forward slashes in SQLAlchemy URLs
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + _sqlite_file.replace("\\", "/")

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Logged-in browser session length (Flask permanent session)
    _timeout_min = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "60"))
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=_timeout_min)

    # QR payload timestamp must be within this many seconds of server time
    QR_VALIDITY_SECONDS = int(os.environ.get("QR_VALIDITY_SECONDS", "300"))

    # Optional: if register form sends this exact secret, user is created as admin
    ADMIN_REGISTRATION_SECRET = os.environ.get("ADMIN_REGISTRATION_SECRET", "") or None
