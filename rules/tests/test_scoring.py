"""db/scoring.sql: precision and recall per rule, against fraud_labels."""

from datetime import timedelta
from pathlib import Path

from tests.conftest import KICKOFF, make_bet, make_player, run, settle

SCORING = (Path(__file__).resolve().parents[2] / "db" / "scoring.sql").read_text()


def score(conn):
    cur = conn.execute(SCORING)
    names = [c.name for c in cur.description]
    return {row[0]: dict(zip(names, row, strict=True)) for row in cur.fetchall()}


def plant(conn, entity_type, entity_id, pattern):
    conn.execute(
        """
        INSERT INTO fraud_labels (entity_type, entity_id, pattern_code, injected_at)
        VALUES (%s, %s, %s, %s)
        """,
        (entity_type, entity_id, pattern, KICKOFF),
    )


def test_scoring_counts_caught_missed_and_false_alarms(conn):
    before = score(conn)["SETTLEMENT_MISMATCH"]
    player = make_player(conn)
    paid_too_much = settle(conn, make_bet(conn, player, KICKOFF, odds="2.000"), "won", "25.00")
    lost_but_paid = settle(conn, make_bet(conn, player, KICKOFF, odds="2.000"), "lost", "12.00")
    # labelled, but its payout is right: nothing in the row for any rule to see
    looks_right = settle(conn, make_bet(conn, player, KICKOFF, odds="2.000"), "won", "20.00")
    honest_but_odd = settle(conn, make_bet(conn, player, KICKOFF, odds="2.000"), "won", "30.00")
    plant(conn, "settlement", paid_too_much, "SETTLEMENT_ERROR")
    plant(conn, "settlement", lost_but_paid, "SETTLEMENT_ERROR")
    plant(conn, "settlement", looks_right, "SETTLEMENT_ERROR")
    assert honest_but_odd                 # not planted: a false alarm when flagged
    run(conn, "SETTLEMENT_MISMATCH")

    after = score(conn)["SETTLEMENT_MISMATCH"]
    change = {k: after[k] - before[k] for k in ("planted", "detected", "caught", "false_alarms", "missed")}
    assert change == {"planted": 3, "detected": 3, "caught": 2, "false_alarms": 1, "missed": 1}


def test_fraud_the_rule_has_not_looked_at_yet_is_not_missed(conn):
    before = score(conn)["LATE_BET"]
    bet = make_bet(conn, make_player(conn), KICKOFF + timedelta(minutes=3))
    plant(conn, "bet", bet, "LATE_BET")        # planted, but LATE_BET has not run since
    after = score(conn)["LATE_BET"]
    assert after["planted"] == before["planted"] and after["missed"] == before["missed"]
