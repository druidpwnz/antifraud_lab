"""Players, and what belongs to one player: balance, transactions, bets.

An unknown player is a 404 on every one of these, never an empty 200. "Player 5 has
no transactions" and "there is no player 5" are different answers, and a client
that mistypes an id should find out.
"""

from http import HTTPStatus
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from psycopg import sql
from pydantic import AwareDatetime

from app import errors
from app.db import get_conn
from app.pagination import PageParams, build_page
from app.schemas.bets import BetStatus, BetSummary, BetSummaryPage
from app.schemas.players import Balance, Player, PlayerPage, PlayerStatus
from app.schemas.transactions import PaymentMethod, Transaction, TransactionPage

router = APIRouter(prefix="/players", tags=["players"])

PLAYER_COLUMNS = sql.SQL("id, registered_at, country, currency, status")


@router.get(
    "",
    summary="List players",
    response_model=PlayerPage,
    responses=errors.responses(400),
)
def list_players(
    page: PageParams = Depends(),
    country: str | None = Query(None, pattern="^[A-Z]{2}$", examples=["UA"]),
    status: PlayerStatus | None = None,
    # AwareDatetime rejects "2026-09-01T12:00:00" with a 422: without an offset it
    # could mean any timezone. The caller has to say "...Z" or "...+03:00".
    registered_after: AwareDatetime | None = None,
    conn: psycopg.Connection = Depends(get_conn),
) -> PlayerPage:
    # Built from fixed SQL fragments with psycopg.sql - never from the caller's input.
    # Every value goes in as a parameter, so this is not the f-string-in-SQL mistake
    # even though the WHERE clause is assembled at runtime.
    conditions = [sql.SQL("id > %(after_id)s")]
    params: dict = {"after_id": page.after_id, "limit": page.limit + 1}

    if country is not None:
        conditions.append(sql.SQL("country = %(country)s"))
        params["country"] = country
    if status is not None:
        conditions.append(sql.SQL("status = %(status)s"))
        params["status"] = status
    if registered_after is not None:
        conditions.append(sql.SQL("registered_at > %(registered_after)s"))
        params["registered_after"] = registered_after

    query = sql.SQL(
        "SELECT {columns} FROM players WHERE {where} ORDER BY id LIMIT %(limit)s"
    ).format(columns=PLAYER_COLUMNS, where=sql.SQL(" AND ").join(conditions))

    rows = conn.execute(query, params).fetchall()
    return build_page(rows, page, Player.model_validate, PlayerPage)


@router.get(
    "/{player_id}",
    summary="One player",
    response_model=Player,
    responses=errors.responses(404),
)
def get_player(
    player_id: int = Path(gt=0),
    conn: psycopg.Connection = Depends(get_conn),
) -> Player:
    return Player.model_validate(load_player(conn, player_id))


def load_player(conn: psycopg.Connection, player_id: int) -> dict:
    """The player's row, or a 404. Shared by every /players/{id}/... endpoint."""
    row = conn.execute(
        sql.SQL("SELECT {columns} FROM players WHERE id = %s").format(columns=PLAYER_COLUMNS),
        (player_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, f"Player {player_id} does not exist.")
    return row


@router.get(
    "/{player_id}/balance",
    summary="A player's balance, and what it is made of",
    response_model=Balance,
    responses=errors.responses(404),
)
def get_balance(
    player_id: int = Path(gt=0),
    conn: psycopg.Connection = Depends(get_conn),
) -> Balance:
    player = load_player(conn, player_id)

    # The same ledger as generator/state.py:load_balances, for one player. Four scalar
    # subqueries rather than one big join: joining transactions to bets would multiply
    # every deposit by every bet and the sums would be wrong.
    totals = conn.execute(
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

    return Balance(
        player_id=player_id,
        currency=player["currency"],
        balance=totals["deposited"] - totals["withdrawn"] - totals["staked"] + totals["paid_out"],
        **totals,
    )


@router.get(
    "/{player_id}/transactions",
    summary="A player's deposits and withdrawals",
    response_model=TransactionPage,
    responses=errors.responses(400, 404),
)
def list_transactions(
    player_id: int = Path(gt=0),
    page: PageParams = Depends(),
    direction: Literal["deposit", "withdrawal"] | None = None,
    status: Literal["pending", "approved", "rejected", "chargeback"] | None = None,
    since: AwareDatetime | None = Query(None, description="Only transactions created after this."),
    conn: psycopg.Connection = Depends(get_conn),
) -> TransactionPage:
    load_player(conn, player_id)

    conditions = [sql.SQL("t.player_id = %(player_id)s"), sql.SQL("t.id > %(after_id)s")]
    params: dict = {"player_id": player_id, "after_id": page.after_id, "limit": page.limit + 1}
    if direction is not None:
        conditions.append(sql.SQL("t.direction = %(direction)s"))
        params["direction"] = direction
    if status is not None:
        conditions.append(sql.SQL("t.status = %(status)s"))
        params["status"] = status
    if since is not None:
        conditions.append(sql.SQL("t.created_at > %(since)s"))
        params["since"] = since

    query = sql.SQL(
        """
        SELECT t.id, t.direction, t.amount, t.currency, t.status, t.created_at, t.processed_at,
               m.id AS method_id, m.type AS method_type, m.last4 AS method_last4
        FROM transactions t
        JOIN payment_methods m ON m.id = t.method_id
        WHERE {where}
        ORDER BY t.id
        LIMIT %(limit)s
        """
    ).format(where=sql.SQL(" AND ").join(conditions))

    rows = conn.execute(query, params).fetchall()
    return build_page(rows, page, transaction_from_row, TransactionPage)


def transaction_from_row(row: dict) -> Transaction:
    # The joined method columns come back flat; the response nests them.
    return Transaction(
        **{k: v for k, v in row.items() if not k.startswith("method_")},
        method=PaymentMethod(id=row["method_id"], type=row["method_type"], last4=row["method_last4"]),
    )


@router.get(
    "/{player_id}/bets",
    summary="A player's bets",
    response_model=BetSummaryPage,
    responses=errors.responses(400, 404),
)
def list_bets(
    player_id: int = Path(gt=0),
    page: PageParams = Depends(),
    status: BetStatus | None = None,
    conn: psycopg.Connection = Depends(get_conn),
) -> BetSummaryPage:
    load_player(conn, player_id)

    conditions = [sql.SQL("b.player_id = %(player_id)s"), sql.SQL("b.id > %(after_id)s")]
    params: dict = {"player_id": player_id, "after_id": page.after_id, "limit": page.limit + 1}
    if status is not None:
        conditions.append(sql.SQL("b.status = %(status)s"))
        params["status"] = status

    # LEFT JOIN LATERAL ... LIMIT 1, not a plain LEFT JOIN: the schema does not stop a
    # bet having two settlement rows, and a plain join would then return that bet
    # twice - and a duplicated row breaks cursor pagination. The generator never
    # settles twice (invariants.sql checks it), but the API should not depend on that.
    query = sql.SQL(
        """
        SELECT b.id, b.placed_at, b.stake, b.currency, b.total_odds, b.status,
               s.payout, s.settled_at
        FROM bets b
        LEFT JOIN LATERAL (
            SELECT payout, settled_at FROM settlements
            WHERE bet_id = b.id
            ORDER BY settled_at DESC
            LIMIT 1
        ) s ON true
        WHERE {where}
        ORDER BY b.id
        LIMIT %(limit)s
        """
    ).format(where=sql.SQL(" AND ").join(conditions))

    rows = conn.execute(query, params).fetchall()
    return build_page(rows, page, BetSummary.model_validate, BetSummaryPage)
