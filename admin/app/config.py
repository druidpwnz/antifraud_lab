"""Settings, read once from the environment (and admin/.env, via python-dotenv)."""

import logging
import os
import secrets
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    api_url: str
    api_key: str
    secret_key: str
    api_timeout: float
    admin_users: str = ""            # "name:hash,name:hash" - see app/auth.py
    session_hours: float = 8
    secure_cookies: bool = False     # True once the panel is served over HTTPS


def load(overrides: dict | None = None) -> Config:
    """The environment, with `overrides` on top (tests use those)."""
    overrides = overrides or {}
    secret_key = overrides.get("secret_key") or os.environ.get("SECRET_KEY", "")
    if not secret_key:
        # Fine for a first run, wrong for anything else: a random key per process means
        # every restart signs everyone out. Said loudly so it gets fixed.
        log.warning("SECRET_KEY is not set - using a random one; restarts will log everyone out")
        secret_key = secrets.token_urlsafe(32)
    values = {
        "api_url": os.environ.get("API_URL", "http://127.0.0.1:8000"),
        "api_key": os.environ.get("API_KEY", ""),
        "api_timeout": float(os.environ.get("API_TIMEOUT", "5")),
        "admin_users": os.environ.get("ADMIN_USERS", ""),
        "session_hours": float(os.environ.get("SESSION_HOURS", "8")),
        "secure_cookies": os.environ.get("SECURE_COOKIES", "0") == "1",
        **overrides,
        "secret_key": secret_key,
    }
    return Config(**values)
