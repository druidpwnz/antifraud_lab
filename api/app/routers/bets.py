"""One bet in full.

Listing bets lives under /players/{id}/bets; this is the detail view, reached from
there by id.
"""

from http import HTTPStatus

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path

from app import errors
from app.db import get_conn
from app.schemas.bets import BetDetail, Leg, LegEvent, LegMarket

router = APIRouter(prefix="/bets", tags=["bets"])


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
