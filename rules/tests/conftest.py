"""Shared fixtures for the rules tests.

They run against the test database the API tests use, antifraud_test (create it
once with `bash reset.sh antifraud_test`, then `python db/migrate.py` on it). Each
test runs inside one transaction that is rolled back at the end, so nothing it
inserts survives - and the API's fixture data is left as it was.

Before a test, every rule's last_id is moved to the newest row already there, so
the rules see only the rows the test makes.
"""

import itertools
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runner  # noqa: E402

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "dbname=antifraud_test")
KICKOFF = datetime(2026, 8, 20, 19, 0, tzinfo=UTC)

_teams = itertools.count(1)


@pytest.fixture
def conn():
    with psycopg.connect(TEST_DATABASE_URL, options="-c timezone=UTC") as connection:
        for rule in runner.RULES:
            connection.execute(
                f"""
                INSERT INTO rule_state (rule_code, last_id)
                VALUES (%s, (SELECT coalesce(max(id), 0) FROM {rule.source}))
                ON CONFLICT (rule_code) DO UPDATE SET last_id = EXCLUDED.last_id
                """,
                (rule.code,),
            )
        yield connection
        connection.rollback()


def run(conn, code):
    """Run one rule by its code; returns the runner's Result."""
    rule = next(r for r in runner.RULES if r.code == code)
    return runner.run_rule(conn, rule)


def alerts(conn, code):
    return conn.execute(
        "SELECT player_id, severity, details FROM alerts WHERE rule_code = %s ORDER BY id",
        (code,),
    ).fetchall()


def make_player(conn) -> int:
    return conn.execute(
        "INSERT INTO players (registered_at, country, currency) VALUES (%s, 'DE', 'EUR') RETURNING id",
        (KICKOFF - timedelta(days=30),),
    ).fetchone()[0]


def make_match(conn, kickoff=KICKOFF) -> int:
    """A match with one 1x2 market; returns the 'home' selection's id."""
    n = next(_teams)
    event_id = conn.execute(
        """
        INSERT INTO events (sport, league, home_team, away_team, start_time)
        VALUES ('football', 'Test League', %s, %s, %s) RETURNING id
        """,
        (f"Home {n}", f"Away {n}", kickoff),
    ).fetchone()[0]
    market_id = conn.execute(
        "INSERT INTO markets (event_id, type, line) VALUES (%s, '1x2', 0) RETURNING id", (event_id,)
    ).fetchone()[0]
    return conn.execute(
        """
        INSERT INTO selections (market_id, outcome, name, current_odds)
        VALUES (%s, 'home', 'Home', 2.00) RETURNING id
        """,
        (market_id,),
    ).fetchone()[0]


def make_bet(conn, player, placed_at, stake="10.00", legs=None, odds="2.000") -> int:
    legs = legs if legs is not None else [make_match(conn)]
    bet_id = conn.execute(
        """
        INSERT INTO bets (player_id, placed_at, stake, currency, total_odds)
        VALUES (%s, %s, %s, 'EUR', %s) RETURNING id
        """,
        (player, placed_at, Decimal(stake), Decimal(odds)),
    ).fetchone()[0]
    for selection in legs:
        conn.execute(
            "INSERT INTO bet_selections (bet_id, selection_id, odds_at_placement) VALUES (%s, %s, 2.00)",
            (bet_id, selection),
        )
    return bet_id


def settle(conn, bet, result, payout, settled_at=KICKOFF + timedelta(hours=2)) -> int:
    conn.execute("UPDATE bets SET status = %s WHERE id = %s", (result, bet))
    return conn.execute(
        "INSERT INTO settlements (bet_id, result, payout, settled_at) VALUES (%s, %s, %s, %s) RETURNING id",
        (bet, result, Decimal(payout), settled_at),
    ).fetchone()[0]
