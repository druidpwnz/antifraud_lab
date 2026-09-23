# planted fraud
#
# Every pattern writes a row to fraud_labels, with enough detail in the jsonb to
# explain afterwards what was done and why a rule should have caught it.
# fraud_labels is ground truth for scoring. Detection rules must never read it.

import json
import random
from datetime import timedelta
from decimal import Decimal

import betting
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


def maybe_late_bets(conn, hour, hour_end, active_players, balances):
    """Bets written after the match has already kicked off.

    Normal betting cannot produce these: load_open_selections only offers matches
    starting after the current hour. So this goes round it deliberately, and prices
    the bet at the last pre-match odds - move_odds stops touching a selection once
    its match starts, which is exactly the stale price a late bettor wants.
    """
    if not config.INJECT_FRAUD:
        return

    in_play = None
    for player in active_players:
        if not helpers.chance(config.LATE_BET_RATE):
            continue
        balance = balances.get(player["id"], Decimal("0.00"))
        if balance < Decimal(config.MIN_STAKE):
            continue

        if in_play is None:
            in_play = load_in_play_selections(conn, hour)
        if not in_play:
            return

        selection_id, odds, event_id, start_time = random.choice(in_play)

        # the bet must land while the match is still being played: after kickoff,
        # before the final whistle, and inside this hour
        final_whistle = start_time + timedelta(minutes=config.MATCH_MINUTES)
        placed_at = helpers.after(player, 20, 900, min(hour_end, final_whistle))
        if placed_at is None:
            continue

        settings = config.ARCHETYPES[player["archetype"]]
        stake = min(
            helpers.money(random.lognormvariate(settings["stake_mu"], settings["stake_sigma"]),
                          minimum=config.MIN_STAKE),
            balance,
        )
        total_odds = odds.quantize(Decimal("0.001"))

        bet_id = betting.place_bet(
            conn, player, placed_at, [(selection_id, odds, event_id)], stake, total_odds
        )
        balances[player["id"]] = balance - stake

        label(conn, "bet", bet_id, "LATE_BET", placed_at, {
            "event_id": event_id,
            "seconds_after_kickoff": int((placed_at - start_time).total_seconds()),
            "odds_at_placement": str(odds),
        })


def load_in_play_selections(conn, hour):
    """Selections on matches that have started but are not over yet."""
    return conn.execute(
        """
        SELECT s.id, s.current_odds, m.event_id, e.start_time
        FROM selections s
        JOIN markets m ON m.id = s.market_id
        JOIN events e  ON e.id = m.event_id
        WHERE e.status = 'scheduled'
          AND s.status = 'open'
          AND e.start_time <= %s
          AND e.start_time + (%s * interval '1 minute') > %s
        ORDER BY s.id
        """,
        (hour, config.MATCH_MINUTES, hour),
    ).fetchall()


def maybe_stake_escalation(conn, hour_end, active_players, balances, open_selections):
    """One bet far larger than anything this player has staked before.

    The shape of an account takeover: weeks of small bets, then someone else empties
    the balance in one go. Competes with honest high-rollers, whose stakes are
    log-normal and occasionally large on their own - which is what makes the
    threshold on the detecting rule something you have to earn from the data.
    """
    if not config.INJECT_FRAUD or not open_selections:
        return

    for player in active_players:
        placed = player.get("bets_placed", 0)
        if placed < config.ESCALATION_MIN_BETS:
            continue
        if not helpers.chance(config.STAKE_ESCALATION_RATE):
            continue

        balance = balances.get(player["id"], Decimal("0.00"))
        average = player["stake_total"] / placed
        if balance < average * Decimal(str(config.ESCALATION_MIN_MULTIPLE)):
            continue        # not enough money for the bet to look anomalous

        placed_at = helpers.after(player, 20, 900, hour_end)
        if placed_at is None:
            continue

        multiple = Decimal(str(round(random.uniform(*config.ESCALATION_MULTIPLE), 2)))
        stake = min(helpers.money(average * multiple, minimum=config.MIN_STAKE), balance)

        selection_id, odds, event_id = random.choice(open_selections)
        bet_id = betting.place_bet(
            conn, player, placed_at, [(selection_id, odds, event_id)],
            stake, odds.quantize(Decimal("0.001")),
        )
        balances[player["id"]] = balance - stake

        label(conn, "bet", bet_id, "STAKE_ESCALATION", placed_at, {
            "average_stake": str(average.quantize(Decimal("0.01"))),
            "stake": str(stake),
            "multiple_of_average": str((stake / average).quantize(Decimal("0.01"))),
            "bets_before": placed,
        })
