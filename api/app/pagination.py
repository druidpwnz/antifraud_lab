"""Cursor pagination.

A page is fetched with `WHERE id > <last id seen> ORDER BY id LIMIT <n>`, rather than
`OFFSET <n>`. The live generator inserts rows all the time, and offsets shift under
inserts: a row added before your current position pushes everything along by one, so
the next page repeats a row or skips one. A cursor says "carry on after id 4812",
which means the same thing no matter what was inserted meanwhile.

It is also faster: OFFSET 100000 makes Postgres read and throw away 100000 rows,
while `id > 4812` is a single index lookup.

Two directions, `order=asc` (oldest first, the default) and `order=desc` (newest
first). Note what each one does with rows created while you page:

  asc   new rows have higher ids, so they turn up on a later page
  desc  new rows have higher ids than where you STARTED, so they never appear -
        to see them, start again from the top. That is how every newest-first feed
        works, and it is the price of never skipping or repeating a row.

The cursor is opaque on purpose. Clients get a token and send it back; they must not
build one themselves. That leaves room to change what is inside - as this module has
already done once, adding the direction - without breaking anyone.

Every router asks this module for the cursor condition and the ORDER BY, instead of
writing `id > ...` itself, so the direction logic exists in exactly one place.
"""

import base64
import binascii
from typing import Generic, Literal, TypeVar

from fastapi import HTTPException, Query, status
from psycopg import sql
from pydantic import BaseModel, Field

T = TypeVar("T")

Order = Literal["asc", "desc"]

_PREFIX = "id:"   # a version marker of sorts: a cursor from something else fails to decode


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page. null on the last page."
    )


def encode(last_id: int, order: Order = "asc") -> str:
    raw = f"{_PREFIX}{order}:{last_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str, order: Order = "asc") -> int:
    """The id to carry on from. 400 if the cursor was not made by encode(), or was made
    for the other direction."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        if not raw.startswith(_PREFIX):
            raise ValueError("wrong prefix")
        body = raw.removeprefix(_PREFIX)
        if ":" in body:
            made_for, _, number = body.partition(":")
        else:
            # A cursor from before `order` existed ("id:4812"): those were all ascending.
            # Accepting it is cheap, and a client mid-way through paging keeps working.
            made_for, number = "asc", body
        if made_for not in ("asc", "desc"):
            raise ValueError("unknown order")
        last_id = int(number)
        if last_id < 0:
            raise ValueError("negative id")
    except (ValueError, binascii.Error, UnicodeDecodeError):
        # 400, not 422: the parameter is well-formed as a string, but it is not a
        # cursor this API issued. The client sent something it should not have.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor.")

    if made_for != order:
        # "after 4812" means opposite things in the two directions. Using an ascending
        # cursor for a descending page would silently return the wrong rows.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"This cursor was made for order={made_for}; ask with the same order.",
        )
    return last_id


class PageParams:
    """`limit`, `cursor` and `order` query parameters, shared by every list endpoint."""

    def __init__(
        self,
        limit: int = Query(20, ge=1, le=100, description="Items per page, 1 to 100."),
        cursor: str | None = Query(None, description="`next_cursor` from the previous page."),
        order: Order = Query("asc", description="`asc` oldest first, `desc` newest first."),
    ):
        self.limit = limit
        self.order = order
        self.last_id = decode(cursor, order) if cursor else None

    def after_cursor(self, *column: str) -> sql.Composable:
        """The WHERE condition that starts this page where the last one ended.

        `column` is the id column, optionally qualified: after_cursor("t", "id").
        On the first page there is nothing to start after, so the condition is TRUE.
        """
        if self.last_id is None:
            return sql.SQL("TRUE")
        operator = ">" if self.order == "asc" else "<"
        return sql.SQL("{column} {operator} %(cursor_id)s").format(
            column=sql.Identifier(*column), operator=sql.SQL(operator)
        )

    def order_by(self, *column: str) -> sql.Composable:
        direction = "ASC" if self.order == "asc" else "DESC"
        return sql.SQL("{column} {direction}").format(
            column=sql.Identifier(*column), direction=sql.SQL(direction)
        )

    def params(self) -> dict:
        """The parameters after_cursor() and the LIMIT need. Fetches one row more than
        the page holds - see build_page."""
        return {"cursor_id": self.last_id, "limit": self.limit + 1}


def build_page(rows: list, params: PageParams, to_item, page_class: type[Page] = Page) -> Page:
    """Turn `limit + 1` fetched rows into a page.

    Fetching one row more than asked for is how we know whether a next page exists,
    without a second COUNT(*) query: if the extra row came back, there is more.
    """
    has_more = len(rows) > params.limit
    rows = rows[: params.limit]
    items = [to_item(row) for row in rows]
    next_cursor = encode(rows[-1]["id"], params.order) if has_more else None
    return page_class(items=items, next_cursor=next_cursor)
