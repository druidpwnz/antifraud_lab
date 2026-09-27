"""Settings, read once from the environment.

Plain os.environ rather than pydantic-settings: four values do not justify another
dependency. Defaults are for local development; a container overrides them.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_keys: tuple[str, ...]
    pool_min: int
    pool_max: int


def load() -> Settings:
    keys = os.environ.get("API_KEYS", "dev-key-change-me")
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "dbname=antifraud"),
        api_keys=tuple(k.strip() for k in keys.split(",") if k.strip()),
        pool_min=int(os.environ.get("POOL_MIN", "1")),
        pool_max=int(os.environ.get("POOL_MAX", "10")),
    )
