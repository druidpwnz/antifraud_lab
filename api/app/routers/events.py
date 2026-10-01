"""Events (matches), and the markets and selections you can bet on."""

from http import HTTPStatus
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from psycopg import sql
from pydantic import AwareDatetime

from app import errors
from app.db import get_conn
from app.pagination import PageParams, build_page
from app.schemas.events import EventDetail, EventPage, EventStatus, EventSummary, Market, Selection

router = APIRouter(prefix="/events", tags=["events"])

EVENT_COLUMNS = sql.SQL(
    "id, sport, league, home_team, away_team, start_time, status, finished_at"
)


@router.get(
    "",
    summary="List events",
    description="Ordered by id unless `sort=start_time`, which lists matches in kickoff "
    "order - ties broken by id, so paging never skips a match that shares a kickoff "
    "time. Filter with `from` and `to` to get a kickoff window.",
    response_model=EventPage,
    responses=errors.responses(400),
)
def list_events(
    page: PageParams = Depends(),
    sort: Literal["id", "start_time"] = Query(
        "id", description="`id` (default) or `start_time`, kickoff order."
    ),
    status: EventStatus | None = None,
    league: str | None = Query(None, min_length=1, max_length=100, examples=["Premier League"]),
    # `from` is a Python keyword, so it cannot be a parameter name. alias= keeps the
    # public name `from` while the code uses starts_from.
    starts_from: AwareDatetime | None = Query(
        None, alias="from", description="Kickoff at or after this time."
    ),
    starts_to: AwareDatetime | None = Query(
        None, alias="to", description="Kickoff strictly before this time."
    ),
    conn: psycopg.Connection = Depends(get_conn),
) -> EventPage:
    if starts_from is not None and starts_to is not None and starts_from >= starts_to:
        # plain 422: the HTTPStatus name for it only exists from Python 3.13
        raise HTTPException(422, "`from` must be earlier than `to`.")

    page.sorted_by(sort)
    conditions = [page.after_cursor()]
    params = page.params()
    if status is not None:
        conditions.append(sql.SQL("status = %(status)s"))
        params["status"] = status
    if league is not None:
        conditions.append(sql.SQL("league = %(league)s"))
        params["league"] = league
    # A half-open window, [from, to): a match exactly on the boundary belongs to
    # exactly one of two back-to-back windows, never to both and never to neither.
    if starts_from is not None:
        conditions.append(sql.SQL("start_time >= %(starts_from)s"))
        params["starts_from"] = starts_from
    if starts_to is not None:
        conditions.append(sql.SQL("start_time < %(starts_to)s"))
        params["starts_to"] = starts_to

    query = sql.SQL(
        "SELECT {columns} FROM events WHERE {where} ORDER BY {order} LIMIT %(limit)s"
    ).format(columns=EVENT_COLUMNS, where=sql.SQL(" AND ").join(conditions),
             order=page.order_by())

    rows = conn.execute(query, params).fetchall()
    return build_page(rows, page, EventSummary.model_validate, EventPage)


@router.get(
    "/{event_id}",
    summary="One event, with every market and selection",
    response_model=EventDetail,
    responses=errors.responses(404),
)
def get_event(
    event_id: int = Path(gt=0),
    conn: psycopg.Connection = Depends(get_conn),
) -> EventDetail:
    event = conn.execute(
        sql.SQL("SELECT {columns} FROM events WHERE id = %s").format(columns=EVENT_COLUMNS),
        (event_id,),
    ).fetchone()
    if event is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, f"Event {event_id} does not exist.")

    # One query for every market and selection, then grouped in Python. LEFT JOIN so
    # a market with no selections still shows up, as an empty list.
    rows = conn.execute(
        """
        SELECT m.id AS market_id, m.type, m.line, m.status AS market_status,
               s.id AS selection_id, s.outcome, s.name, s.current_odds,
               s.status AS selection_status
        FROM markets m
        LEFT JOIN selections s ON s.market_id = m.id
        WHERE m.event_id = %s
        ORDER BY m.id, s.id
        """,
        (event_id,),
    ).fetchall()

    markets: dict[int, Market] = {}      # dicts keep insertion order, so ORDER BY survives
    for row in rows:
        market = markets.get(row["market_id"])
        if market is None:
            market = Market(
                id=row["market_id"], type=row["type"], line=row["line"],
                status=row["market_status"], selections=[],
            )
            markets[row["market_id"]] = market
        if row["selection_id"] is not None:
            market.selections.append(Selection(
                id=row["selection_id"], outcome=row["outcome"], name=row["name"],
                current_odds=row["current_odds"], status=row["selection_status"],
            ))

    return EventDetail(**event, markets=list(markets.values()))
