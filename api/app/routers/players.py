"""Players."""

from http import HTTPStatus

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from psycopg import sql
from pydantic import AwareDatetime

from app import errors
from app.db import get_conn
from app.pagination import PageParams, build_page
from app.schemas.players import Player, PlayerPage, PlayerStatus

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
    row = conn.execute(
        sql.SQL("SELECT {columns} FROM players WHERE id = %s").format(columns=PLAYER_COLUMNS),
        (player_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, f"Player {player_id} does not exist.")
    return Player.model_validate(row)
