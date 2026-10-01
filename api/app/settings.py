"""Settings, read once from the environment.

Plain os.environ rather than pydantic-settings: a handful of values does not justify
another dependency. Defaults are for local development; a container overrides them.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_keys: tuple[str, ...]           # full access: read, and create risk checks
    pool_min: int
    pool_max: int
    api_read_keys: tuple[str, ...] = ()  # read only - what the admin panel gets


def _key_list(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(k.strip() for k in os.environ.get(name, default).split(",") if k.strip())


def load() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "dbname=antifraud"),
        api_keys=_key_list("API_KEYS", "dev-key-change-me"),
        api_read_keys=_key_list("API_READ_KEYS"),
        pool_min=int(os.environ.get("POOL_MIN", "1")),
        pool_max=int(os.environ.get("POOL_MAX", "10")),
    )
