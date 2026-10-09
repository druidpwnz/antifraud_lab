# placing bets
#
# A bet is a row in `bets` plus one row per leg in `bet_selections`.
# total_odds is the product of the legs' odds AT PLACEMENT - a historical fact.
# It is stored, not recomputed later, because the selection's price keeps moving.

import random
from datetime import timedelta
from decimal import Decimal

import config
import helpers


def load_open_selections(conn, limit):
    """Selections you can still bet on: matches that start inside the betting window.

    `limit` is the latest a bet from this tick can be placed. Only matches starting
    after it are offered, so an ordinary bet is never placed after kickoff - that
    is reserved for the planted late bets.

    ORDER BY is not decoration - the caller picks from this list with a seeded random,
    so an undefined row order would make the whole run irreproducible.
    """
    return conn.execute(
        """
        SELECT s.id, s.current_odds, e.id
        FROM selections s
        JOIN markets m ON m.id = s.market_id
        JOIN events e  ON e.id = m.event_id
        WHERE e.status = 'scheduled'
          AND m.status = 'open'
          AND s.status = 'open'
          AND e.start_time >  %s
          AND e.start_time <= %s
        ORDER BY s.id
        """,
        (limit, limit + timedelta(hours=config.BET_WINDOW_HOURS)),
    ).fetchall()


def create_bets(conn, limit, active_players, balances, open_selections):
    """Each active player with money places a few bets."""
    if not open_selections:
        return

    for player in active_players:
        balance = balances.get(player["id"], Decimal("0.00"))
        settings = config.ARCHETYPES[player["archetype"]]
        how_many_bets = random.randint(*settings["bets_per_session"])

        for _ in range(how_many_bets):
            if balance < Decimal(config.MIN_STAKE):
                break
            placed_at = helpers.after(player, *config.ACTION_GAP_SECONDS, limit)
            if placed_at is None:
                break        # no time left in this session

            legs = pick_legs(open_selections)
            total_odds = combined_odds(legs)

            stake = helpers.money(
                random.lognormvariate(settings["stake_mu"], settings["stake_sigma"]),
                minimum=config.MIN_STAKE,
            )
            stake = min(stake, balance)      # never bet more than you have

            place_bet(conn, player, placed_at, legs, stake, total_odds)

            # running history, so the fraud injector knows what "normal" looks like
            # for this player. The planted bet is deliberately not counted here.
            player["bets_placed"] = player.get("bets_placed", 0) + 1
            player["stake_total"] = player.get("stake_total", Decimal("0.00")) + stake

            balance = balance - stake
            balances[player["id"]] = balance


def place_bet(conn, player, placed_at, legs, stake, total_odds):
    """Write one bet and its legs. Used by normal betting and by the fraud injector."""
    bet_id = conn.execute(
        """
        INSERT INTO bets (player_id, placed_at, stake, currency, total_odds)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (player["id"], placed_at, stake, player["currency"], total_odds),
    ).fetchone()[0]

    for selection_id, odds, *_rest in legs:
        conn.execute(
            """
            INSERT INTO bet_selections (bet_id, selection_id, odds_at_placement)
            VALUES (%s, %s, %s)
            """,
            (bet_id, selection_id, odds),
        )
    return bet_id


def pick_legs(open_selections):
    """One selection for a single, or 2-4 from different matches for a combo."""
    if not helpers.chance(config.COMBO_CHANCE):
        return [random.choice(open_selections)]

    wanted = random.randint(*config.COMBO_LEGS)
    sample_size = min(len(open_selections), wanted * 5)

    legs, used_events = [], set()
    for selection in random.sample(open_selections, sample_size):
        event_id = selection[2]
        if event_id in used_events:
            continue         # two legs on the same match would be linked outcomes
        used_events.add(event_id)
        legs.append(selection)
        if len(legs) == wanted:
            break
    return legs


def combined_odds(legs):
    """Multiply the legs together. numeric(10,3) in the schema, so 3 decimals."""
    total = Decimal(1)
    for _selection_id, odds, _event_id in legs:
        total = total * odds
    return max(total.quantize(Decimal("0.001")), Decimal("1.001"))
