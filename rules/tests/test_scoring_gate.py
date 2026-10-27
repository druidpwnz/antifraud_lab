"""The CI gate must fail closed, including when rounded dashboard scores look OK."""

from pathlib import Path

import psycopg
import pytest

from tests.conftest import KICKOFF, make_bet, make_player

GATE = (Path(__file__).resolve().parents[2] / "db/tests/scoring_gate.sql").read_text()


@pytest.fixture
def gate(conn):
    # Shadow only the scores in this transaction to exercise precise boundaries.
    # The stack job exercises the real view against the full generated seed.
    conn.execute("CREATE TEMP TABLE gate_scores (rule_code text, planted bigint, caught bigint)")
    conn.execute("""
        INSERT INTO gate_scores VALUES
            ('LATE_BET', 100, 100), ('SETTLEMENT_MISMATCH', 100, 100), ('STAKE_ANOMALY', 100, 85)
    """)
    conn.execute("CREATE TEMP VIEW rule_scores AS SELECT * FROM gate_scores")
    return conn


def test_exact_recall_floors_pass(gate):
    gate.execute(GATE)


@pytest.mark.parametrize("code", ["LATE_BET", "SETTLEMENT_MISMATCH", "STAKE_ANOMALY"])
def test_each_rule_below_its_floor_fails(gate, code):
    gate.execute("UPDATE gate_scores SET caught = caught - 1 WHERE rule_code = %s", (code,))
    with pytest.raises(psycopg.errors.RaiseException, match="below recall floor"):
        gate.execute(GATE)


@pytest.mark.parametrize("code,caught", [("LATE_BET", 1999), ("STAKE_ANOMALY", 1699)])
def test_rounding_cannot_hide_a_miss(gate, code, caught):
    gate.execute("UPDATE gate_scores SET planted = 2000, caught = %s WHERE rule_code = %s", (caught, code))
    with pytest.raises(psycopg.errors.RaiseException, match="below recall floor"):
        gate.execute(GATE)


@pytest.mark.parametrize("change", [
    "DELETE FROM gate_scores WHERE rule_code = 'LATE_BET'",
    "UPDATE gate_scores SET planted = 0 WHERE rule_code = 'LATE_BET'",
    "UPDATE gate_scores SET caught = NULL WHERE rule_code = 'LATE_BET'",
])
def test_missing_ground_truth_cannot_pass(gate, change):
    gate.execute(change)
    with pytest.raises(psycopg.errors.RaiseException, match="no scored ground truth"):
        gate.execute(GATE)


def test_missing_rule_state_cannot_pass(gate):
    gate.execute("DELETE FROM rule_state WHERE rule_code = 'LATE_BET'")
    with pytest.raises(psycopg.errors.RaiseException, match="has not scanned the full seed"):
        gate.execute(GATE)


def test_unscanned_rows_cannot_pass_even_with_perfect_scores(gate):
    make_bet(gate, make_player(gate), KICKOFF)
    with pytest.raises(psycopg.errors.RaiseException, match="has not scanned the full seed"):
        gate.execute(GATE)
