# planted fraud
#
# Every pattern writes a row to fraud_labels, with enough detail in the jsonb to
# explain afterwards what was done and why a rule should have caught it.
# fraud_labels is ground truth for scoring. Detection rules must never read it.

import json
import random
from decimal import Decimal

import config
import helpers


def label(conn, entity_type, entity_id, pattern_code, injected_at,
          details=None, cluster_id=None):
    """Record one planted thing. details goes in as jsonb."""
    conn.execute(
        """
        INSERT INTO fraud_labels
            (entity_type, entity_id, pattern_code, cluster_id, details, injected_at)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s)
        """,
        (entity_type, entity_id, pattern_code, cluster_id,
         json.dumps(details or {}, default=str), injected_at),
    )


def break_settlement(result, correct_payout, stake, total_odds):
    """Maybe pay the wrong amount on this bet.

    Returns (payout, details). details is None when nothing was planted, which is
    almost always. Two shapes:

      wrong_amount  - a won bet paid too much or too little. The obvious rule
                      (abs(payout - stake * total_odds) > 0.01 on won bets) sees it.
      lost_bet_paid - a losing bet paid out anyway. That same rule does NOT see it,
                      because its WHERE clause only looks at result = 'won'.
    """
    if not config.INJECT_FRAUD or not helpers.chance(config.SETTLEMENT_ERROR_RATE):
        return correct_payout, None

    if result == "won":
        offset = Decimal(str(round(random.uniform(*config.SETTLEMENT_ERROR_OFFSET), 3)))
        if helpers.chance(0.5):
            offset = -offset
        payout = helpers.money(correct_payout * (Decimal(1) + offset))
        if abs(payout - correct_payout) <= Decimal("0.01"):
            payout = correct_payout + Decimal("0.05")     # keep it detectable
        return payout, {
            "variant": "wrong_amount",
            "correct_payout": str(correct_payout),
            "offset": str(offset),
        }

    share = Decimal(str(round(random.uniform(0.5, 1.0), 3)))
    payout = helpers.money(stake * total_odds * share)
    return payout, {
        "variant": "lost_bet_paid",
        "correct_payout": "0.00",
        "share_of_full_win": str(share),
    }
