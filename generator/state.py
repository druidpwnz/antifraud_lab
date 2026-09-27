# rebuilding in-memory state from the database
#
# The backfill builds players and balances as it goes. The live generator starts
# with nothing, so it reads them back out of the database.
#
# The rule this whole design follows: anything the live generator needs must be
# either stored in a table or derivable from (seed, row id). Nothing may exist only
# in a Python variable. Archetypes, event probabilities and withdrawal due times are
# all derived; balances and player details are read back from rows.

from decimal import Decimal

import players


def load(conn, sim_time):
    """Rebuild (all_players, balances) as the backfill would have had them.

    Every player's clock is set to sim_time: all their past actions happened before
    the resume point, so that is a safe lower bound for their next one.
    """
    all_players = {}
    for player_id, country, currency in conn.execute(
        "SELECT id, country, currency FROM players WHERE status = 'active' ORDER BY id"
    ).fetchall():
        all_players[player_id] = {
            "id": player_id,
            "country": country,
            "currency": currency,
            "archetype": players.archetype_for(player_id),   # derived, never stored
            "clock": sim_time,
        }

    # the device is the same in every session, so the latest one is fine
    for player_id, device_id, user_agent in conn.execute(
        """
        SELECT DISTINCT ON (player_id) player_id, device_id, user_agent
        FROM sessions
        ORDER BY player_id, started_at DESC
        """
    ).fetchall():
        if player_id in all_players:
            all_players[player_id].update(device_id=device_id, user_agent=user_agent)

    # The home IP is the one they use MOST, not the one they used last: 15% of
    # sessions come from a throwaway address (mobile, travel) without the player
    # moving house. Taking the latest session's IP would make a one-off address
    # permanent for that player after the handoff.
    # Ties go to the earliest address seen, which is the one used at registration.
    for player_id, ip in conn.execute(
        """
        SELECT DISTINCT ON (player_id) player_id, ip
        FROM (
            SELECT player_id, ip, count(*) AS times_used, min(started_at) AS first_seen
            FROM sessions
            GROUP BY player_id, ip
        ) per_ip
        ORDER BY player_id, times_used DESC, first_seen
        """
    ).fetchall():
        if player_id in all_players:
            all_players[player_id]["ip"] = ip

    # first payment method, which is the one the generator uses
    for player_id, method_id, method_type, fingerprint, last4 in conn.execute(
        """
        SELECT DISTINCT ON (player_id) player_id, id, type, fingerprint, last4
        FROM payment_methods
        ORDER BY player_id, added_at
        """
    ).fetchall():
        if player_id in all_players:
            all_players[player_id].update(
                method_id=method_id, method_type=method_type,
                fingerprint=fingerprint, last4=last4,
            )

    # betting history, for the stake-escalation pattern. Planted bets are excluded,
    # exactly as they are when the backfill counts them.
    for player_id, bets_placed, stake_total in conn.execute(
        """
        SELECT b.player_id, count(*), sum(b.stake)
        FROM bets b
        WHERE NOT EXISTS (
            SELECT 1 FROM fraud_labels f
            WHERE f.entity_type = 'bet' AND f.entity_id = b.id
        )
        GROUP BY b.player_id
        """
    ).fetchall():
        if player_id in all_players:
            all_players[player_id].update(bets_placed=bets_placed, stake_total=stake_total)

    # how many deposits they have made, for the first-deposit chance
    for player_id, deposit_count in conn.execute(
        """
        SELECT player_id, count(*)
        FROM transactions
        WHERE direction = 'deposit'
        GROUP BY player_id
        """
    ).fetchall():
        if player_id in all_players:
            all_players[player_id]["deposit_count"] = deposit_count

    balances = load_balances(conn)

    # a player with no session or no payment method cannot act; the generator always
    # creates both at registration, so this should never drop anyone
    usable = [p for p in all_players.values() if "device_id" in p and "method_id" in p]
    return usable, balances


def load_balances(conn):
    """Balance per player: approved deposits - withdrawals - stakes + payouts.

    Withdrawals count from the moment they are requested, not when they are approved,
    because that is when the generator takes the money out of the balance.
    """
    rows = conn.execute(
        """
        WITH ledger AS (
            SELECT player_id, amount AS delta
            FROM transactions
            WHERE direction = 'deposit' AND status = 'approved'
          UNION ALL
            SELECT player_id, -amount
            FROM transactions
            WHERE direction = 'withdrawal' AND status <> 'rejected'
          UNION ALL
            SELECT player_id, -stake
            FROM bets
          UNION ALL
            SELECT b.player_id, s.payout
            FROM settlements s
            JOIN bets b ON b.id = s.bet_id
        )
        SELECT player_id, sum(delta)
        FROM ledger
        GROUP BY player_id
        """
    ).fetchall()
    return {player_id: Decimal(total) for player_id, total in rows}
