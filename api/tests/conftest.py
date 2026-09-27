"""Shared test fixtures.

Tests run against a separate database, antifraud_test, never the one the generator
writes to. Create it once with:

    bash reset.sh antifraud_test

Override the connection with TEST_DATABASE_URL.
"""

import os
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "dbname=antifraud_test")
API_KEY = "test-key"

COUNTRIES = ["UA", "PL", "DE", "GB", "ES"]
CURRENCY = {"UA": "UAH", "PL": "PLN", "DE": "EUR", "GB": "GBP", "ES": "EUR"}
FIRST_REGISTRATION = datetime(2026, 8, 1, tzinfo=timezone.utc)
PLAYER_COUNT = 25


def fixture_player(n: int) -> dict:
    """Player number n (1-based) of the fixture set. Tests use this to know what to expect."""
    country = COUNTRIES[n % len(COUNTRIES)]
    status = {7: "suspended", 14: "suspended", 21: "closed"}.get(n, "active")
    return {
        "id": n,
        "registered_at": FIRST_REGISTRATION + timedelta(hours=n),
        "country": country,
        "currency": CURRENCY[country],
        "status": status,
    }


@pytest.fixture(scope="session")
def seeded_db():
    """Wipe the test database once per test run and load a small known dataset."""
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        dbname = conn.info.dbname
        # TRUNCATE ... CASCADE empties every table that references players. Refuse to
        # do that anywhere but a database whose name says it is for tests.
        if not dbname.endswith("_test"):
            pytest.exit(f"refusing to wipe '{dbname}': test database names must end in _test")

        has_schema = conn.execute("SELECT to_regclass('public.players') IS NOT NULL").fetchone()[0]
        if not has_schema:
            pytest.exit(f"'{dbname}' has no schema - run: bash reset.sh {dbname}")

        conn.execute("TRUNCATE players RESTART IDENTITY CASCADE")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO players (registered_at, country, currency, status) "
                "VALUES (%(registered_at)s, %(country)s, %(currency)s, %(status)s)",
                [fixture_player(n) for n in range(1, PLAYER_COUNT + 1)],
            )
    yield


@pytest.fixture
def client(monkeypatch, seeded_db):
    """A client wired to the test database, sending a valid API key by default.
    `with` runs the app's lifespan, so the pool opens before the test and closes after."""
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("API_KEYS", API_KEY)
    from app.main import app

    with TestClient(app, headers={"X-API-Key": API_KEY}) as c:
        yield c


@pytest.fixture
def client_without_db(monkeypatch):
    """A client pointed at a database that cannot exist, for testing the failure path."""
    monkeypatch.setenv("DATABASE_URL", "host=127.0.0.1 port=1 dbname=nowhere connect_timeout=1")
    from app.main import app

    with TestClient(app) as c:
        yield c
