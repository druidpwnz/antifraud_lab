"""Risk rules for a proposed deposit or withdrawal.

Pure functions: facts about the player go in, a decision comes out. No database, no
HTTP, no clock - the caller fetches the facts and supplies "now". That is what makes
every rule testable on its own, with a hand-built Facts and no fixtures.

Two kinds of rule:

  hard  - a single one declines outright (score 100): the player is not active, the
          currency is wrong, a withdrawal is more than the balance.
  soft  - each adds points; the total decides:
          under REVIEW_AT approve, under DECLINE_AT review, otherwise decline.

Known simplification: amount thresholds such as NEW_ACCOUNT_AMOUNT are in the
player's own currency, so 200 UAH and 200 GBP are treated the same. A real system
would convert to one currency first.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

REVIEW_AT = 30
DECLINE_AT = 60

FAR_ABOVE_USUAL_MULTIPLE = 10          # times the player's median approved deposit
VELOCITY_WINDOW = timedelta(hours=1)
VELOCITY_DEPOSITS = 3                  # this many deposits already in the window
NEW_ACCOUNT_AGE = timedelta(hours=24)
NEW_ACCOUNT_AMOUNT = Decimal("200")
PASSTHROUGH_WINDOW = timedelta(hours=1)
PASSTHROUGH_MAX_TURNOVER = Decimal("0.10")   # staked less than 10% of the deposit


@dataclass(frozen=True)
class Proposed:
    """The transaction being asked about."""

    direction: str      # "deposit" or "withdrawal"
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class Facts:
    """Everything the rules need to know about the player, as of `now`."""

    now: datetime                           # the SIMULATED clock, not the wall clock
    player_status: str
    player_currency: str
    registered_at: datetime
    balance: Decimal
    median_deposit: Decimal | None          # None: no approved deposit yet
    deposits_last_hour: int
    last_deposit_amount: Decimal | None
    last_deposit_at: datetime | None
    staked_since_last_deposit: Decimal


@dataclass(frozen=True)
class Reason:
    code: str
    message: str
    points: int


@dataclass(frozen=True)
class Result:
    decision: str       # "approve", "review" or "decline"
    score: int          # 0..100
    reasons: list[Reason]


def score(proposed: Proposed, facts: Facts) -> Result:
    hard = hard_declines(proposed, facts)
    if hard:
        return Result("decline", 100, hard)

    reasons = soft_signals(proposed, facts)
    total = min(100, sum(r.points for r in reasons))
    if total >= DECLINE_AT:
        decision = "decline"
    elif total >= REVIEW_AT:
        decision = "review"
    else:
        decision = "approve"
    return Result(decision, total, reasons)


def hard_declines(p: Proposed, f: Facts) -> list[Reason]:
    """Every hard rule that fails - all of them, not just the first, so the caller
    sees the whole picture at once."""
    reasons = []
    if f.player_status != "active":
        reasons.append(Reason("player_not_active", f"The player is {f.player_status}.", 100))
    if p.currency != f.player_currency:
        reasons.append(Reason(
            "currency_mismatch",
            f"The player's currency is {f.player_currency}, not {p.currency}.",
            100,
        ))
    if p.direction == "withdrawal" and p.amount > f.balance:
        reasons.append(Reason(
            "insufficient_funds",
            f"A withdrawal of {p.amount} is more than the balance of {f.balance}.",
            100,
        ))
    return reasons


def soft_signals(p: Proposed, f: Facts) -> list[Reason]:
    reasons = []

    if f.median_deposit is not None and p.amount > f.median_deposit * FAR_ABOVE_USUAL_MULTIPLE:
        reasons.append(Reason(
            "amount_far_above_usual",
            f"{p.amount} is more than {FAR_ABOVE_USUAL_MULTIPLE}x the player's median "
            f"deposit of {f.median_deposit}.",
            40,
        ))

    if p.direction == "deposit" and f.deposits_last_hour >= VELOCITY_DEPOSITS:
        reasons.append(Reason(
            "deposit_velocity",
            f"{f.deposits_last_hour} deposits already in the last hour.",
            30,
        ))

    if f.now - f.registered_at < NEW_ACCOUNT_AGE and p.amount > NEW_ACCOUNT_AMOUNT:
        reasons.append(Reason(
            "new_account_large_amount",
            f"The account is under {NEW_ACCOUNT_AGE.total_seconds() / 3600:.0f} hours old "
            f"and the amount is over {NEW_ACCOUNT_AMOUNT}.",
            25,
        ))

    # Money in and straight back out, with almost no betting in between: the shape of
    # using the book to move money rather than to gamble.
    if (
        p.direction == "withdrawal"
        and f.last_deposit_at is not None
        and f.now - f.last_deposit_at < PASSTHROUGH_WINDOW
        and f.staked_since_last_deposit < f.last_deposit_amount * PASSTHROUGH_MAX_TURNOVER
    ):
        reasons.append(Reason(
            "passthrough",
            f"Withdrawing within an hour of depositing {f.last_deposit_amount}, "
            f"with only {f.staked_since_last_deposit} staked since.",
            35,
        ))

    return reasons
