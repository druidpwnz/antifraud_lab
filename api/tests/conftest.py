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

# Player 1 has a small, hand-checkable money history. Player 2 has nothing at all.
#   deposits:    100.00 approved, 50.00 approved, 30.00 rejected   -> deposited 150.00
#   withdrawals:  40.00 approved, 10.00 pending                    -> withdrawn  50.00
#   bets:         20.00 won (paid 45.00), 15.00 lost, 5.00 open    -> staked 40.00, paid_out 45.00
#   balance = 150.00 - 50.00 - 40.00 + 45.00 = 105.00
PLAYER_WITH_MONEY = 1
PLAYER_WITH_NOTHING = 2

# Risk-check players, measured against the simulated clock SIM_NOW:
#   player 3 deposited 400.00 thirty minutes ago and has not bet since - passthrough shape
#   player 4 made three 20.00 deposits in the last hour - velocity
#   player 7 is suspended (see fixture_player)
PASSTHROUGH_PLAYER = 3
VELOCITY_PLAYER = 4
SUSPENDED_PLAYER = 7


def at(day: int, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc)


SIM_NOW = at(12, 10)

FIXTURE_TRANSACTIONS = [
    # direction, amount, status, created_at, processed_at
    ("deposit", "100.00", "approved", at(2), at(2, 10, 1)),
    ("deposit", "50.00", "approved", at(3), at(3, 10, 1)),
    ("deposit", "30.00", "rejected", at(4), at(4, 10, 1)),
    ("withdrawal", "40.00", "approved", at(5), at(5, 13)),
    ("withdrawal", "10.00", "pending", at(6), None),
]

# Three matches. The first is over; the other two have not kicked off.
#   selections: (outcome, name, current_odds, status)
FIXTURE_EVENTS = [
    {
        "league": "Premier League", "home_team": "Arsenal", "away_team": "Chelsea",
        "start_time": at(8, 12), "status": "finished", "finished_at": at(8, 13, 50),
        "markets": [
            ("1x2", "0", "settled", [
                ("home", "Arsenal", "2.25", "won"),
                ("draw", "Draw", "3.40", "lost"),
                ("away", "Chelsea", "3.10", "lost"),
            ]),
            ("total_goals", "2.5", "settled", [
                ("over", "Over 2.5", "1.80", "lost"),
                ("under", "Under 2.5", "2.05", "won"),
            ]),
        ],
    },
    {
        "league": "La Liga", "home_team": "Real Madrid", "away_team": "Barcelona",
        "start_time": at(10, 19), "status": "scheduled", "finished_at": None,
        "markets": [
            # current odds 1.50, but bet 3 was placed at 1.55: the price has moved since
            ("1x2", "0", "open", [
                ("home", "Real Madrid", "1.50", "open"),
                ("draw", "Draw", "4.00", "open"),
                ("away", "Barcelona", "5.20", "open"),
            ]),
        ],
    },
    {
        "league": "Bundesliga", "home_team": "Bayern Munich", "away_team": "Borussia Dortmund",
        "start_time": at(11, 17, 30), "status": "scheduled", "finished_at": None,
        "markets": [
            ("1x2", "0", "open", [
                ("home", "Bayern Munich", "2.00", "open"),
                ("draw", "Draw", "3.60", "open"),
                ("away", "Borussia Dortmund", "3.40", "open"),
            ]),
        ],
    },
]

FIXTURE_BETS = [
    # stake, total_odds, status, placed_at, (result, payout, settled_at) or None,
    # legs: (event index, market index, outcome, odds_at_placement)
    # total_odds is the product of the legs' odds, as the generator guarantees.
    ("20.00", "2.250", "won", at(7), ("won", "45.00", at(8, 14)),
     [(0, 0, "home", "2.25")]),
    ("15.00", "1.800", "lost", at(8), ("lost", "0.00", at(8, 14)),
     [(0, 1, "over", "1.80")]),
    ("5.00", "3.100", "open", at(9), None,
     [(1, 0, "home", "1.55"), (2, 0, "home", "2.00")]),    # 1.55 x 2.00 = 3.100
]


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
        has_risk_checks = conn.execute("SELECT to_regclass('public.risk_checks') IS NOT NULL").fetchone()[0]
        if not has_risk_checks:
            pytest.exit(f"'{dbname}' is missing migration 003 - run: bash reset.sh {dbname}")

        # events too: nothing about players references them, so CASCADE from players
        # alone would leave old matches behind and their ids would keep growing
        conn.execute("TRUNCATE players, events RESTART IDENTITY CASCADE")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO players (registered_at, country, currency, status) "
                "VALUES (%(registered_at)s, %(country)s, %(currency)s, %(status)s)",
                [fixture_player(n) for n in range(1, PLAYER_COUNT + 1)],
            )
        selection_ids = load_events(conn)
        load_money_history(conn, PLAYER_WITH_MONEY, selection_ids)
        load_risk_histories(conn)
        # the simulated clock the risk checks measure against
        conn.execute(
            "INSERT INTO sim_state (id, sim_time, seed, days) VALUES (1, %s, 42, 14) "
            "ON CONFLICT (id) DO UPDATE SET sim_time = EXCLUDED.sim_time",
            (SIM_NOW,),
        )
    yield


def load_risk_histories(conn: psycopg.Connection) -> None:
    """Deposits for the passthrough and velocity players. No bets for either."""
    histories = {
        PASSTHROUGH_PLAYER: [("400.00", at(12, 9, 25))],
        VELOCITY_PLAYER: [("20.00", at(12, 9, 10)), ("20.00", at(12, 9, 20)), ("20.00", at(12, 9, 40))],
    }
    for player_id, deposits in histories.items():
        method_id = conn.execute(
            "INSERT INTO payment_methods (player_id, type, fingerprint, added_at) "
            "VALUES (%s, 'crypto', %s, %s) RETURNING id",
            (player_id, f"{player_id:02d}" * 32, at(2, 9)),
        ).fetchone()[0]
        for amount, created_at in deposits:
            conn.execute(
                "INSERT INTO transactions (player_id, method_id, direction, amount, currency, "
                "status, created_at, processed_at) VALUES (%s, %s, 'deposit', %s, %s, 'approved', %s, %s)",
                (player_id, method_id, amount, fixture_player(player_id)["currency"],
                 created_at, created_at + timedelta(minutes=5)),
            )


def load_events(conn: psycopg.Connection) -> dict[tuple, int]:
    """Insert FIXTURE_EVENTS. Returns (event index, market index, outcome) -> selection id."""
    selection_ids = {}
    for e_index, event in enumerate(FIXTURE_EVENTS):
        event_id = conn.execute(
            "INSERT INTO events (sport, league, home_team, away_team, start_time, status, finished_at) "
            "VALUES ('football', %s, %s, %s, %s, %s, %s) RETURNING id",
            (event["league"], event["home_team"], event["away_team"],
             event["start_time"], event["status"], event["finished_at"]),
        ).fetchone()[0]
        for m_index, (market_type, line, market_status, selections) in enumerate(event["markets"]):
            market_id = conn.execute(
                "INSERT INTO markets (event_id, type, line, status) VALUES (%s, %s, %s, %s) RETURNING id",
                (event_id, market_type, line, market_status),
            ).fetchone()[0]
            for outcome, name, odds, status in selections:
                selection_ids[(e_index, m_index, outcome)] = conn.execute(
                    "INSERT INTO selections (market_id, outcome, name, current_odds, status) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (market_id, outcome, name, odds, status),
                ).fetchone()[0]
    return selection_ids


def load_money_history(conn: psycopg.Connection, player_id: int, selection_ids: dict) -> None:
    currency = fixture_player(player_id)["currency"]
    method_id = conn.execute(
        "INSERT INTO payment_methods (player_id, type, fingerprint, last4, added_at) "
        "VALUES (%s, 'card', %s, '4242', %s) RETURNING id",
        (player_id, "ab" * 32, at(2, 9)),
    ).fetchone()[0]

    for direction, amount, status, created_at, processed_at in FIXTURE_TRANSACTIONS:
        conn.execute(
            "INSERT INTO transactions (player_id, method_id, direction, amount, currency, "
            "status, created_at, processed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (player_id, method_id, direction, amount, currency, status, created_at, processed_at),
        )

    for stake, total_odds, status, placed_at, settlement, legs in FIXTURE_BETS:
        bet_id = conn.execute(
            "INSERT INTO bets (player_id, placed_at, stake, currency, total_odds, status) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (player_id, placed_at, stake, currency, total_odds, status),
        ).fetchone()[0]
        for e_index, m_index, outcome, odds_at_placement in legs:
            conn.execute(
                "INSERT INTO bet_selections (bet_id, selection_id, odds_at_placement) VALUES (%s, %s, %s)",
                (bet_id, selection_ids[(e_index, m_index, outcome)], odds_at_placement),
            )
        if settlement:
            result, payout, settled_at = settlement
            conn.execute(
                "INSERT INTO settlements (bet_id, result, payout, settled_at) VALUES (%s, %s, %s, %s)",
                (bet_id, result, payout, settled_at),
            )


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
