"""Cursor pagination.

A page is fetched with `WHERE id > <last id seen> ORDER BY id LIMIT <n>`, rather than
`OFFSET <n>`. The live generator inserts rows all the time, and offsets shift under
inserts: a row added before your current position pushes everything along by one, so
the next page repeats a row or skips one. A cursor says "carry on after id 4812",
which means the same thing no matter what was inserted meanwhile. New rows get
higher ids and simply turn up on a later page.

It is also faster: OFFSET 100000 makes Postgres read and throw away 100000 rows,
while `id > 4812` is a single index lookup.

The cursor is opaque on purpose. Clients get a token and send it back; they must not
build one themselves. That leaves room to change what is inside (a timestamp, a
second sort key) without breaking anyone.
"""

import base64
import binascii
from typing import Generic, TypeVar

from fastapi import HTTPException, Query, status
from pydantic import BaseModel, Field

T = TypeVar("T")

_PREFIX = "id:"   # a version marker of sorts: a cursor from something else fails to decode


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page. null on the last page."
    )


def encode(last_id: int) -> str:
    raw = f"{_PREFIX}{last_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str) -> int:
    """The id to carry on after. 400 if the cursor was not made by encode()."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        if not raw.startswith(_PREFIX):
            raise ValueError("wrong prefix")
        last_id = int(raw.removeprefix(_PREFIX))
        if last_id < 0:
            raise ValueError("negative id")
        return last_id
    except (ValueError, binascii.Error, UnicodeDecodeError):
        # 400, not 422: the parameter is well-formed as a string, but it is not a
        # cursor this API issued. The client sent something it should not have.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor.")


class PageParams:
    """`limit` and `cursor` query parameters, shared by every list endpoint."""

    def __init__(
        self,
        limit: int = Query(20, ge=1, le=100, description="Items per page, 1 to 100."),
        cursor: str | None = Query(None, description="`next_cursor` from the previous page."),
    ):
        self.limit = limit
        self.after_id = decode(cursor) if cursor else 0


def build_page(rows: list, params: PageParams, to_item, page_class: type[Page] = Page) -> Page:
    """Turn `limit + 1` fetched rows into a page.

    Fetching one row more than asked for is how we know whether a next page exists,
    without a second COUNT(*) query: if the extra row came back, there is more.
    """
    has_more = len(rows) > params.limit
    rows = rows[: params.limit]
    items = [to_item(row) for row in rows]
    next_cursor = encode(rows[-1]["id"]) if has_more else None
    return page_class(items=items, next_cursor=next_cursor)
