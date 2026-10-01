"""Bets: the list across every player, and one bet in full.

A single player's bets are also at /players/{id}/bets. Both lists run the same query,
bet_summary_page(), so they cannot drift apart.
"""

from decimal import Decimal
from http import HTTPStatus

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from psycopg import sql
from pydantic import AwareDatetime

from app import errors
from app.db import get_conn
from app.pagination import PageParams, build_page
from app.schemas.bets import (
    BetDetail,
    BetStatus,
    BetSummary,
    BetSummaryPage,
    Leg,
    LegEvent,
    LegMarket,
)

router = APIRouter(prefix="/bets", tags=["bets"])


@router.get(
    "",
    summary="Bets across every player",
    description="The back-office view of what is happening. Usually asked for with "
    "`order=desc`, newest first.",
    response_model=BetSummaryPage,
    responses=errors.responses(400),
)
def list_bets(
    page: PageParams = Depends(),
    status: BetStatus | None = None,
    min_stake: Decimal | None = Query(
        None, ge=0, decimal_places=2, description="Only bets staking at least this much.",
        examples=["500.00"],
    ),
    placed_after: AwareDatetime | None = None,
    conn: psycopg.Connection = Depends(get_conn),
) -> BetSummaryPage:
    conditions: list[sql.Composable] = []
    params: dict = {}
    if status is not None:
        conditions.append(sql.SQL("b.status = %(status)s"))
        params["status"] = status
    if min_stake is not None:
        conditions.append(sql.SQL("b.stake >= %(min_stake)s"))
        params["min_stake"] = min_stake
    if placed_after is not None:
        conditions.append(sql.SQL("b.placed_at > %(placed_after)s"))
        params["placed_after"] = placed_after

    return bet_summary_page(conn, page, conditions, params)


def bet_summary_page(
    conn: psycopg.Connection,
    page: PageParams,
    conditions: list[sql.Composable],
    params: dict,
) -> BetSummaryPage:
    """One page of bets matching `conditions`, each with its settlement if it has one.

    LEFT JOIN LATERAL ... LIMIT 1, not a plain LEFT JOIN: the schema does not stop a
    bet having two settlement rows, and a plain join would then return that bet
    twice - and a duplicated row breaks cursor pagination. The generator never
    settles twice (invariants.sql checks it), but the API should not depend on that.
    """
    where = sql.SQL(" AND ").join([*conditions, page.after_cursor("b", "id")])
    query = sql.SQL(
        """
        SELECT b.id, b.player_id, b.placed_at, b.stake, b.currency, b.total_odds,
               b.status, s.payout, s.settled_at
        FROM bets b
        LEFT JOIN LATERAL (
            SELECT payout, settled_at FROM settlements
            WHERE bet_id = b.id
            ORDER BY settled_at DESC
            LIMIT 1
        ) s ON true
        WHERE {where}
        ORDER BY {order}
        LIMIT %(limit)s
        """
    ).format(where=where, order=page.order_by("b", "id"))

    rows = conn.execute(query, {**params, **page.params()}).fetchall()
    return build_page(rows, page, BetSummary.model_validate, BetSummaryPage)


@router.get(
    "/{bet_id}",
    summary="One bet, with its legs and settlement",
    response_model=BetDetail,
    responses=errors.responses(404),
)
def get_bet(
    bet_id: int = Path(gt=0),
    conn: psycopg.Connection = Depends(get_conn),
) -> BetDetail:
    # Three small queries rather than one join. One join would repeat the bet's
    # columns on every leg row and need un-picking in Python; three lookups by
    # primary or foreign key are just as fast and much easier to read. (This is not
    # the N+1 problem: that is one query per item in a LIST. Here it is always three.)
    bet = conn.execute(
        "SELECT id, player_id, placed_at, stake, currency, total_odds, status "
        "FROM bets WHERE id = %s",
        (bet_id,),
    ).fetchone()
    if bet is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, f"Bet {bet_id} does not exist.")

    legs = conn.execute(
        """
        SELECT bs.selection_id, s.outcome, s.name, bs.odds_at_placement,
               s.status AS selection_status,
               m.id AS market_id, m.type AS market_type, m.line AS market_line,
               e.id AS event_id, e.league, e.home_team, e.away_team, e.start_time,
               e.status AS event_status
        FROM bet_selections bs
        JOIN selections s ON s.id = bs.selection_id
        JOIN markets m    ON m.id = s.market_id
        JOIN events e     ON e.id = m.event_id
        WHERE bs.bet_id = %s
        ORDER BY e.start_time, bs.selection_id
        """,
        (bet_id,),
    ).fetchall()

    # latest one, for the same reason as the LATERAL in /players/{id}/bets: the schema
    # does not forbid a second settlement row
    settlement = conn.execute(
        "SELECT result, payout, settled_at FROM settlements "
        "WHERE bet_id = %s ORDER BY settled_at DESC LIMIT 1",
        (bet_id,),
    ).fetchone()

    return BetDetail(**bet, legs=[leg_from_row(r) for r in legs], settlement=settlement)


def leg_from_row(row: dict) -> Leg:
    return Leg(
        selection_id=row["selection_id"],
        outcome=row["outcome"],
        name=row["name"],
        odds_at_placement=row["odds_at_placement"],
        selection_status=row["selection_status"],
        market=LegMarket(id=row["market_id"], type=row["market_type"], line=row["market_line"]),
        event=LegEvent(
            id=row["event_id"],
            league=row["league"],
            home_team=row["home_team"],
            away_team=row["away_team"],
            start_time=row["start_time"],
            status=row["event_status"],
        ),
    )
