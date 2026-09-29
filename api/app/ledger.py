"""A player's money, from the rows that record it.

Shared by GET /players/{id}/balance and by the risk check's insufficient-funds rule,
so the two can never disagree about how much a player has.
"""

from decimal import Decimal

import psycopg


def totals(conn: psycopg.Connection, player_id: int) -> dict[str, Decimal]:
    """deposited, withdrawn, staked and paid_out for one player.

    The same ledger as generator/state.py:load_balances. Four scalar subqueries rather
    than one join: joining transactions to bets would multiply every deposit by every
    bet, and every sum would be wrong.
    """
    return conn.execute(
        """
        SELECT
          (SELECT coalesce(sum(amount), 0) FROM transactions
           WHERE player_id = %(p)s AND direction = 'deposit' AND status = 'approved') AS deposited,
          (SELECT coalesce(sum(amount), 0) FROM transactions
           WHERE player_id = %(p)s AND direction = 'withdrawal' AND status <> 'rejected') AS withdrawn,
          (SELECT coalesce(sum(stake), 0) FROM bets
           WHERE player_id = %(p)s) AS staked,
          (SELECT coalesce(sum(s.payout), 0) FROM settlements s
           JOIN bets b ON b.id = s.bet_id
           WHERE b.player_id = %(p)s) AS paid_out
        """,
        {"p": player_id},
    ).fetchone()


def balance(t: dict[str, Decimal]) -> Decimal:
    return t["deposited"] - t["withdrawn"] - t["staked"] + t["paid_out"]
