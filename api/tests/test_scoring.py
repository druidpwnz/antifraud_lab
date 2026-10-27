"""The risk rules on their own: no database, no HTTP, a hand-built Facts per test.

This is what writing scoring.py as pure functions buys: each rule is tested by
changing one fact and watching one reason appear.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app import scoring
from app.scoring import Facts, Proposed

NOW = datetime(2026, 8, 12, 10, tzinfo=UTC)

# A boring, established, well-funded player. Every test changes one thing about them.
CALM = Facts(
    now=NOW,
    player_status="active",
    player_currency="EUR",
    registered_at=NOW - timedelta(days=30),
    balance=Decimal("500.00"),
    median_deposit=Decimal("50.00"),
    deposits_last_hour=0,
    last_deposit_amount=Decimal("50.00"),
    last_deposit_at=NOW - timedelta(days=2),
    staked_since_last_deposit=Decimal("40.00"),
)
DEPOSIT = Proposed("deposit", Decimal("50.00"), "EUR")
WITHDRAWAL = Proposed("withdrawal", Decimal("100.00"), "EUR")


def codes(result: scoring.Result) -> list[str]:
    return [r.code for r in result.reasons]


def test_an_ordinary_deposit_is_approved_with_no_reasons():
    result = scoring.score(DEPOSIT, CALM)

    assert (result.decision, result.score, result.reasons) == ("approve", 0, [])


# -------------------------------------------------------------------- hard rules

def test_inactive_player_is_declined():
    result = scoring.score(DEPOSIT, replace(CALM, player_status="suspended"))

    assert (result.decision, result.score) == ("decline", 100)
    assert codes(result) == ["player_not_active"]


def test_wrong_currency_is_declined():
    result = scoring.score(replace(DEPOSIT, currency="GBP"), CALM)

    assert codes(result) == ["currency_mismatch"]
    assert result.decision == "decline"


def test_withdrawing_more_than_the_balance_is_declined():
    result = scoring.score(replace(WITHDRAWAL, amount=Decimal("500.01")), CALM)

    assert codes(result) == ["insufficient_funds"]


def test_withdrawing_exactly_the_balance_is_allowed():
    result = scoring.score(replace(WITHDRAWAL, amount=Decimal("500.00")), CALM)

    assert "insufficient_funds" not in codes(result)


def test_a_large_deposit_is_never_insufficient_funds():
    result = scoring.score(replace(DEPOSIT, amount=Decimal("100.00")), replace(CALM, balance=Decimal("0")))

    assert "insufficient_funds" not in codes(result)


def test_every_failing_hard_rule_is_reported_not_just_the_first():
    facts = replace(CALM, player_status="closed", balance=Decimal("0"))

    result = scoring.score(Proposed("withdrawal", Decimal("10.00"), "GBP"), facts)

    assert codes(result) == ["player_not_active", "currency_mismatch", "insufficient_funds"]


# -------------------------------------------------------------------- soft rules

def test_amount_far_above_usual():
    # median 50, so the line is 500: 500.00 is fine, 500.01 is not
    assert scoring.score(replace(DEPOSIT, amount=Decimal("500.00")), CALM).reasons == []
    result = scoring.score(replace(DEPOSIT, amount=Decimal("500.01")), CALM)

    assert codes(result) == ["amount_far_above_usual"]
    assert (result.decision, result.score) == ("review", 40)


def test_no_deposit_history_means_no_usual_amount_to_compare_with():
    result = scoring.score(replace(DEPOSIT, amount=Decimal("10000")), replace(CALM, median_deposit=None))

    assert "amount_far_above_usual" not in codes(result)


def test_deposit_velocity_counts_only_for_deposits():
    busy = replace(CALM, deposits_last_hour=3)

    assert codes(scoring.score(DEPOSIT, busy)) == ["deposit_velocity"]
    assert "deposit_velocity" not in codes(scoring.score(WITHDRAWAL, busy))
    assert "deposit_velocity" not in codes(scoring.score(DEPOSIT, replace(CALM, deposits_last_hour=2)))


def test_new_account_with_a_large_amount():
    fresh = replace(CALM, registered_at=NOW - timedelta(hours=5))

    assert scoring.score(replace(DEPOSIT, amount=Decimal("200.00")), fresh).reasons == []
    assert codes(scoring.score(replace(DEPOSIT, amount=Decimal("200.01")), fresh)) == ["new_account_large_amount"]


def test_a_day_old_account_is_no_longer_new():
    one_day = replace(CALM, registered_at=NOW - timedelta(hours=24))

    assert scoring.score(replace(DEPOSIT, amount=Decimal("300.00")), one_day).reasons == []


def test_passthrough_needs_a_recent_deposit_and_almost_no_betting():
    just_deposited = replace(
        CALM,
        last_deposit_amount=Decimal("400.00"),
        last_deposit_at=NOW - timedelta(minutes=20),
        staked_since_last_deposit=Decimal("10.00"),     # 2.5% of the deposit
    )

    assert codes(scoring.score(WITHDRAWAL, just_deposited)) == ["passthrough"]
    # betting 10% or more of it is ordinary play
    played = replace(just_deposited, staked_since_last_deposit=Decimal("40.00"))
    assert "passthrough" not in codes(scoring.score(WITHDRAWAL, played))
    # an hour or more later it is just a withdrawal
    later = replace(just_deposited, last_deposit_at=NOW - timedelta(hours=1))
    assert "passthrough" not in codes(scoring.score(WITHDRAWAL, later))


# -------------------------------------------------------------------- thresholds

def test_signals_add_up_and_decide():
    fresh_and_busy = replace(CALM, registered_at=NOW - timedelta(hours=1), deposits_last_hour=3)
    big = replace(DEPOSIT, amount=Decimal("600.00"))

    result = scoring.score(big, fresh_and_busy)

    assert codes(result) == ["amount_far_above_usual", "deposit_velocity", "new_account_large_amount"]
    assert result.score == 95          # 40 + 30 + 25
    assert result.decision == "decline"


def test_score_is_capped_at_100():
    facts = replace(
        CALM,
        registered_at=NOW - timedelta(hours=1),
        last_deposit_amount=Decimal("600.00"),
        last_deposit_at=NOW - timedelta(minutes=5),
        staked_since_last_deposit=Decimal("0"),
        balance=Decimal("10000"),
    )

    result = scoring.score(Proposed("withdrawal", Decimal("600.00"), "EUR"), facts)

    assert sum(r.points for r in result.reasons) == 100      # 40 + 25 + 35
    assert result.score == 100


def test_thresholds():
    assert scoring.REVIEW_AT == 30 and scoring.DECLINE_AT == 60
    velocity_only = scoring.score(DEPOSIT, replace(CALM, deposits_last_hour=3))
    assert (velocity_only.score, velocity_only.decision) == (30, "review")   # exactly on the line
