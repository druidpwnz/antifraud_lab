"""Each rule finds its shape in hand-made rows, and leaves the honest version alone."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import runner
from tests.conftest import KICKOFF, alerts, make_bet, make_match, make_player, run, settle

BEFORE = KICKOFF - timedelta(hours=1)


# ------------------------------------------------------------ SETTLEMENT_MISMATCH

def test_a_won_bet_paid_correctly_is_not_flagged(conn):
    bet = make_bet(conn, make_player(conn), BEFORE, stake="10.00", odds="2.150")
    settle(conn, bet, "won", "21.50")
    run(conn, "SETTLEMENT_MISMATCH")
    assert alerts(conn, "SETTLEMENT_MISMATCH") == []


def test_a_won_bet_paid_too_much_is_flagged_with_the_numbers(conn):
    player = make_player(conn)
    bet = make_bet(conn, player, BEFORE, stake="10.00", odds="2.000")
    settlement = settle(conn, bet, "won", "23.00")
    run(conn, "SETTLEMENT_MISMATCH")
    [(alert_player, severity, details)] = alerts(conn, "SETTLEMENT_MISMATCH")
    assert (alert_player, severity) == (player, "high")
    assert details["settlement_id"] == settlement and details["bet_id"] == bet
    assert Decimal(str(details["expected"])) == Decimal("20.00")
    assert Decimal(str(details["difference"])) == Decimal("3.00")


def test_a_won_bet_paid_too_little_is_flagged(conn):
    bet = make_bet(conn, make_player(conn), BEFORE, stake="10.00", odds="2.000")
    settle(conn, bet, "won", "17.00")
    run(conn, "SETTLEMENT_MISMATCH")
    assert len(alerts(conn, "SETTLEMENT_MISMATCH")) == 1


def test_a_cent_of_rounding_is_not_a_mismatch(conn):
    # 3.33 x 1.505 = 5.01165 -> paid 5.01: off by less than a cent
    bet = make_bet(conn, make_player(conn), BEFORE, stake="3.33", odds="1.505")
    settle(conn, bet, "won", "5.01")
    run(conn, "SETTLEMENT_MISMATCH")
    assert alerts(conn, "SETTLEMENT_MISMATCH") == []


def test_a_lost_bet_paid_nothing_is_not_flagged(conn):
    bet = make_bet(conn, make_player(conn), BEFORE, stake="10.00", odds="2.000")
    settle(conn, bet, "lost", "0.00")
    run(conn, "SETTLEMENT_MISMATCH")
    assert alerts(conn, "SETTLEMENT_MISMATCH") == []


def test_a_lost_bet_that_was_paid_is_flagged(conn):
    """The blind spot of the first version (WHERE result = 'won'). Until phase 9
    step 8 this test asserted the opposite."""
    bet = make_bet(conn, make_player(conn), BEFORE, stake="10.00", odds="2.000")
    settle(conn, bet, "lost", "15.00")
    run(conn, "SETTLEMENT_MISMATCH")
    [(_, _, details)] = alerts(conn, "SETTLEMENT_MISMATCH")
    assert details["result"] == "lost"
    assert Decimal(str(details["expected"])) == Decimal("0.00")
    assert Decimal(str(details["difference"])) == Decimal("15.00")


def test_a_rescan_reads_old_rows_again_without_doubling_alerts(conn):
    player = make_player(conn)
    settle(conn, make_bet(conn, player, BEFORE, stake="10.00", odds="2.000"), "lost", "15.00")
    run(conn, "SETTLEMENT_MISMATCH")
    runner.rescan(conn, "SETTLEMENT_MISMATCH")
    again = run(conn, "SETTLEMENT_MISMATCH")
    everything = conn.execute("SELECT count(*) FROM settlements").fetchone()[0]
    assert again.scanned == everything             # the whole table, from the first row
    mine = [a for a in alerts(conn, "SETTLEMENT_MISMATCH") if a[0] == player]
    assert len(mine) == 1


# ------------------------------------------------------------------------ LATE_BET

def test_a_bet_before_kickoff_is_not_flagged(conn):
    make_bet(conn, make_player(conn), KICKOFF - timedelta(seconds=1))
    run(conn, "LATE_BET")
    assert alerts(conn, "LATE_BET") == []


def test_a_bet_after_kickoff_is_flagged(conn):
    player = make_player(conn)
    bet = make_bet(conn, player, KICKOFF + timedelta(minutes=12))
    run(conn, "LATE_BET")
    [(alert_player, severity, details)] = alerts(conn, "LATE_BET")
    assert (alert_player, severity) == (player, "high")
    assert details["bet_id"] == bet and details["seconds_after_kickoff"] == 720


def test_a_combo_with_one_late_leg_is_flagged_once(conn):
    legs = [make_match(conn, KICKOFF + timedelta(hours=3)), make_match(conn, KICKOFF)]
    make_bet(conn, make_player(conn), KICKOFF + timedelta(minutes=5), legs=legs)
    run(conn, "LATE_BET")
    assert len(alerts(conn, "LATE_BET")) == 1


def test_a_combo_with_two_late_legs_is_still_one_alert(conn):
    legs = [make_match(conn, KICKOFF - timedelta(minutes=30)), make_match(conn, KICKOFF)]
    make_bet(conn, make_player(conn), KICKOFF + timedelta(minutes=5), legs=legs)
    run(conn, "LATE_BET")
    [(_, _, details)] = alerts(conn, "LATE_BET")
    assert details["seconds_after_kickoff"] == 35 * 60      # about the leg that started first


# ------------------------------------------------------------------- STAKE_ANOMALY

def history(conn, player, stakes, start=KICKOFF - timedelta(days=10)):
    """One bet per hour with these stakes; returns the time after the last one."""
    match = make_match(conn, KICKOFF + timedelta(days=5))
    for i, stake in enumerate(stakes):
        make_bet(conn, player, start + timedelta(hours=i), stake=stake, legs=[match])
    return start + timedelta(hours=len(stakes))


def test_a_stake_8x_the_average_after_15_bets_is_flagged(conn):
    player = make_player(conn)
    after = history(conn, player, ["10.00"] * 15)
    bet = make_bet(conn, player, after, stake="80.00")
    run(conn, "STAKE_ANOMALY")
    [(alert_player, severity, details)] = alerts(conn, "STAKE_ANOMALY")
    assert (alert_player, severity) == (player, "medium")
    assert details["bet_id"] == bet and details["bets_before"] == 15
    assert Decimal(str(details["multiple_of_average"])) == Decimal("8.0")


def test_just_under_8x_is_not_flagged(conn):
    player = make_player(conn)
    after = history(conn, player, ["10.00"] * 15)
    make_bet(conn, player, after, stake="79.99")
    run(conn, "STAKE_ANOMALY")
    assert alerts(conn, "STAKE_ANOMALY") == []


def test_without_15_bets_before_there_is_no_normal_to_compare_with(conn):
    player = make_player(conn)
    after = history(conn, player, ["10.00"] * 14)
    make_bet(conn, player, after, stake="500.00")
    run(conn, "STAKE_ANOMALY")
    assert alerts(conn, "STAKE_ANOMALY") == []


def test_only_the_last_50_bets_make_the_average(conn):
    # 10 big bets long ago, then 50 small ones: the big ones have left the window,
    # so a stake of 100 is 10x the small average and is flagged
    player = make_player(conn)
    after = history(conn, player, ["1000.00"] * 10 + ["10.00"] * 50)
    make_bet(conn, player, after, stake="100.00")
    run(conn, "STAKE_ANOMALY")
    assert len(alerts(conn, "STAKE_ANOMALY")) == 1


def test_another_players_history_does_not_count(conn):
    regular, newcomer = make_player(conn), make_player(conn)
    after = history(conn, regular, ["10.00"] * 20)
    make_bet(conn, newcomer, after, stake="500.00")        # newcomer has no history
    run(conn, "STAKE_ANOMALY")
    assert alerts(conn, "STAKE_ANOMALY") == []


def test_history_from_an_earlier_run_still_counts(conn):
    # the 15 small bets are scanned in one run, the big one arrives for the next:
    # the average must still come from the bets the first run already passed
    player = make_player(conn)
    after = history(conn, player, ["10.00"] * 15)
    run(conn, "STAKE_ANOMALY")
    make_bet(conn, player, after, stake="90.00")
    result = run(conn, "STAKE_ANOMALY")
    assert result.scanned == 1
    assert len(alerts(conn, "STAKE_ANOMALY")) == 1


# -------------------------------------------------------------------- the runner

def test_a_second_run_finds_nothing_new_and_alerts_nothing_twice(conn):
    bet = make_bet(conn, make_player(conn), KICKOFF + timedelta(minutes=1))
    first = run(conn, "LATE_BET")
    second = run(conn, "LATE_BET")
    assert (first.scanned, first.created) == (1, 1)
    assert (second.scanned, second.created) == (0, 0)
    assert first.upto == bet
    last_id = conn.execute("SELECT last_id FROM rule_state WHERE rule_code = 'LATE_BET'").fetchone()[0]
    assert last_id == bet


def test_rows_below_last_id_are_never_looked_at_again(conn):
    make_bet(conn, make_player(conn), KICKOFF + timedelta(minutes=1))    # late
    conn.execute("UPDATE rule_state SET last_id = (SELECT max(id) FROM bets) WHERE rule_code = 'LATE_BET'")
    result = run(conn, "LATE_BET")
    assert result.scanned == 0
    assert alerts(conn, "LATE_BET") == []


def test_no_rule_reads_fraud_labels():
    for path in (Path(__file__).resolve().parents[1] / "sql").glob("*.sql"):
        assert "fraud_labels" not in path.read_text(), f"{path.name} reads the ground truth"
