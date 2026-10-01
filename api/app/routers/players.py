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

from app import errors, ledger
from app.db import get_conn
from app.pagination import PageParams, build_page
from app.routers.bets import bet_summary_page
from app.schemas.bets import BetStatus, BetSummaryPage
from app.schemas.players import (
    Balance,
    LinkedPlayer,
    LinkedPlayerPage,
    Player,
    PlayerPage,
    PlayerStatus,
    Session,
    SessionPage,
)
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
    conditions = [page.after_cursor()]
    params = page.params()

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
        "SELECT {columns} FROM players WHERE {where} ORDER BY {order} LIMIT %(limit)s"
    ).format(columns=PLAYER_COLUMNS, where=sql.SQL(" AND ").join(conditions),
             order=page.order_by())

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
    t = ledger.totals(conn, player_id)
    return Balance(
        player_id=player_id,
        currency=player["currency"],
        balance=ledger.balance(t),
        **t,
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

    conditions = [sql.SQL("t.player_id = %(player_id)s"), page.after_cursor("t")]
    params = {**page.params(), "player_id": player_id}
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
        ORDER BY {order}
        LIMIT %(limit)s
        """
    ).format(where=sql.SQL(" AND ").join(conditions), order=page.order_by("t"))

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

    conditions = [sql.SQL("b.player_id = %(player_id)s")]
    params: dict = {"player_id": player_id}
    if status is not None:
        conditions.append(sql.SQL("b.status = %(status)s"))
        params["status"] = status

    return bet_summary_page(conn, page, conditions, params)


@router.get(
    "/{player_id}/sessions",
    summary="A player's logins: when, from which IP, on which device",
    response_model=SessionPage,
    responses=errors.responses(400, 404),
)
def list_sessions(
    player_id: int = Path(gt=0),
    page: PageParams = Depends(),
    conn: psycopg.Connection = Depends(get_conn),
) -> SessionPage:
    load_player(conn, player_id)

    query = sql.SQL(
        """
        SELECT id, started_at, ended_at, host(ip) AS ip, device_id::text AS device_id, user_agent
        FROM sessions
        WHERE player_id = %(player_id)s AND {after}
        ORDER BY {order}
        LIMIT %(limit)s
        """
    ).format(after=page.after_cursor(), order=page.order_by())

    rows = conn.execute(query, {**page.params(), "player_id": player_id}).fetchall()
    return build_page(rows, page, Session.model_validate, SessionPage)


@router.get(
    "/{player_id}/linked",
    summary="Other players sharing a device or a payment method with this one",
    description="For multi-accounting investigations. Says WHO is linked and HOW MANY "
    "devices and payment methods they share - never the device ids or card "
    "fingerprints themselves, which are compared inside the database.",
    response_model=LinkedPlayerPage,
    responses=errors.responses(400, 404),
)
def list_linked(
    player_id: int = Path(gt=0),
    page: PageParams = Depends(),
    conn: psycopg.Connection = Depends(get_conn),
) -> LinkedPlayerPage:
    load_player(conn, player_id)

    # Two kinds of link, gathered into one list, then counted per other player.
    # Both halves are joins on an indexed column - sessions(device_id) and
    # payment_methods(fingerprint) - so this is cheap however big the tables get.
    #
    # UNION, not UNION ALL: it removes duplicate (player, kind, value) rows, so ten
    # sessions on one shared device count as one shared device, not ten. (That also
    # makes the DISTINCTs in the two CTEs unnecessary for correctness - they only
    # shrink what gets joined.)
    query = sql.SQL(
        """
        WITH my_devices AS (
            SELECT DISTINCT device_id FROM sessions WHERE player_id = %(player_id)s
        ),
        my_methods AS (
            SELECT DISTINCT fingerprint FROM payment_methods WHERE player_id = %(player_id)s
        ),
        links AS (
            SELECT s.player_id AS other_id, 'device' AS kind, s.device_id::text AS shared
            FROM sessions s
            JOIN my_devices d ON d.device_id = s.device_id
            WHERE s.player_id <> %(player_id)s
          UNION
            SELECT pm.player_id, 'payment_method', pm.fingerprint
            FROM payment_methods pm
            JOIN my_methods m ON m.fingerprint = pm.fingerprint
            WHERE pm.player_id <> %(player_id)s
        )
        SELECT p.id, p.country, p.status, p.registered_at,
               count(*) FILTER (WHERE l.kind = 'device')         AS shared_devices,
               count(*) FILTER (WHERE l.kind = 'payment_method') AS shared_payment_methods
        FROM links l
        JOIN players p ON p.id = l.other_id
        WHERE {after}
        GROUP BY p.id, p.country, p.status, p.registered_at
        ORDER BY {order}
        LIMIT %(limit)s
        """
    ).format(after=page.after_cursor("p"), order=page.order_by("p"))

    rows = conn.execute(query, {**page.params(), "player_id": player_id}).fetchall()
    return build_page(rows, page, LinkedPlayer.model_validate, LinkedPlayerPage)
