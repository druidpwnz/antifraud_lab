"""The connection pool, and the dependency that lends a connection to a request.

One pool for the whole app, opened at startup and closed at shutdown. Opening a
connection per request costs a TCP handshake and authentication every time; a pool
keeps a few open and hands them out.
"""

from collections.abc import Iterator

import psycopg
from fastapi import Request
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.settings import Settings


def create_pool(settings: Settings) -> ConnectionPool:
    # timezone=UTC on every connection, same as generator/db.py, so timestamps come
    # back as UTC whatever the server or the machine is set to.
    #
    # dict_row: rows come back as {"id": 1, "country": "UA", ...} instead of tuples,
    # so they can be handed straight to a Pydantic model and a reordered SELECT
    # cannot silently put a value in the wrong field.
    #
    # open() does not wait for the database: the app starts even if Postgres is
    # down, and /ready reports that instead of the process refusing to boot.
    pool = ConnectionPool(
        settings.database_url,
        min_size=settings.pool_min,
        max_size=settings.pool_max,
        kwargs={"options": "-c timezone=UTC", "row_factory": dict_row},
        open=False,
    )
    pool.open(wait=False)
    return pool


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    """FastAPI dependency: one pooled connection for the length of a request.

    Leaving the `with` block commits if the request succeeded, rolls back if it
    raised, and returns the connection to the pool either way.
    """
    with request.app.state.pool.connection() as conn:
        yield conn
