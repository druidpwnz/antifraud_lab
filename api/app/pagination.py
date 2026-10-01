"""Cursor pagination.

A page is fetched with `WHERE id > <last id seen> ORDER BY id LIMIT <n>`, rather than
`OFFSET <n>`. The live generator inserts rows all the time, and offsets shift under
inserts: a row added before your current position pushes everything along by one, so
the next page repeats a row or skips one. A cursor says "carry on after id 4812",
which means the same thing no matter what was inserted meanwhile.

It is also faster: OFFSET 100000 makes Postgres read and throw away 100000 rows,
while `id > 4812` is a single index lookup.

Direction
---------
`order=asc` (oldest first, the default) and `order=desc` (newest first). Rows created
while you page: ascending, they turn up on a later page; descending, they are above
where you started and never appear - start again from the top to see them.

Sorting by something other than id
----------------------------------
Events can also be listed in kickoff order. Kickoff times repeat - the generator uses
five a day - so "carry on after 15:00" would skip every other 15:00 match. The id is
added as a tie-breaker, the cursor carries both, and the condition becomes a ROW
COMPARISON:

    (start_time, id) > ('2026-08-10 15:00+00', 482)

which Postgres reads as "a later kickoff, or the same kickoff and a higher id" - the
exact place the last page stopped, ties included. Both columns must be sorted in the
same direction for that to hold.

The cursor is opaque on purpose. Clients get a token and send it back; they must not
build one themselves. Inside it are the sort, the direction and the last row's sort
values - and the format has already changed twice without breaking a client.

Every router asks this module for the cursor condition and the ORDER BY, instead of
writing `id > ...` itself, so all of this exists in exactly one place.
"""

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Literal, TypeVar

from fastapi import HTTPException, Query, status
from psycopg import sql
from pydantic import BaseModel, Field

T = TypeVar("T")

Order = Literal["asc", "desc"]

# Each sort a list can use, and the columns that make it a total order. A sort on a
# column with repeats always ends with id, so no two rows ever tie.
SORTS: dict[str, tuple[str, ...]] = {
    "id": ("id",),
    "start_time": ("start_time", "id"),
}


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page. null on the last page."
    )


@dataclass(frozen=True)
class Cursor:
    sort: str
    order: Order
    values: tuple


# ------------------------------------------------------------- encoding

def encode(sort: str, order: Order, values: tuple) -> str:
    """"<sort>:<order>:<value>|<value>", base64url without padding."""
    parts = "|".join(v.isoformat() if isinstance(v, datetime) else str(v) for v in values)
    raw = f"{sort}:{order}:{parts}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str) -> Cursor:
    """What a cursor says. 400 if this API did not make it."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        sort, _, rest = raw.partition(":")
        if sort not in SORTS:
            raise ValueError("unknown sort")
        if ":" in rest:
            made_for, _, parts = rest.partition(":")
        else:
            # The first cursor format, "id:4812", from before `order` existed. Those
            # were all ascending; a client mid-way through paging keeps working.
            made_for, parts = "asc", rest
        if made_for not in ("asc", "desc"):
            raise ValueError("unknown order")
        values = _parse_values(sort, parts.split("|"))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        # 400, not 422: the parameter is well-formed as a string, but it is not a
        # cursor this API issued. The client sent something it should not have.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor.")
    return Cursor(sort, made_for, values)


def _parse_values(sort: str, parts: list[str]) -> tuple:
    if len(parts) != len(SORTS[sort]):
        raise ValueError("wrong number of values")
    values = []
    for column, part in zip(SORTS[sort], parts):
        if column == "id":
            value = int(part)
            if value < 0:
                raise ValueError("negative id")
        else:
            value = datetime.fromisoformat(part)
            if value.tzinfo is None:
                raise ValueError("time without a zone")
        values.append(value)
    return tuple(values)


# ------------------------------------------------------------ parameters

class PageParams:
    """`limit`, `cursor` and `order` query parameters, shared by every list endpoint.

    A list sorted by anything other than id calls sorted_by() before using it.
    """

    def __init__(
        self,
        limit: int = Query(20, ge=1, le=100, description="Items per page, 1 to 100."),
        cursor: str | None = Query(None, description="`next_cursor` from the previous page."),
        order: Order = Query("asc", description="`asc` oldest first, `desc` newest first."),
    ):
        self.limit = limit
        self.order = order
        self.sort = "id"
        self._cursor = decode(cursor) if cursor else None
        if self._cursor is not None and self._cursor.order != order:
            # "after 4812" means opposite things in the two directions. Using an
            # ascending cursor for a descending page would silently return wrong rows.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"This cursor was made for order={self._cursor.order}; ask with the same order.",
            )

    def sorted_by(self, sort: str) -> "PageParams":
        self.sort = sort
        return self

    def _cursor_values(self) -> tuple | None:
        if self._cursor is None:
            return None
        if self._cursor.sort != self.sort:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"This cursor was made for sort={self._cursor.sort}; ask with the same sort.",
            )
        return self._cursor.values

    def _columns(self, table: str | None) -> list[sql.Identifier]:
        return [sql.Identifier(table, c) if table else sql.Identifier(c) for c in SORTS[self.sort]]

    def after_cursor(self, table: str | None = None) -> sql.Composable:
        """The WHERE condition that starts this page where the last one ended.

        `table` qualifies the columns when the query has several tables:
        after_cursor("t") gives t.id. On the first page there is nothing to start
        after, so the condition is TRUE.
        """
        values = self._cursor_values()
        if values is None:
            return sql.SQL("TRUE")
        operator = ">" if self.order == "asc" else "<"
        placeholders = [sql.Placeholder(f"cursor_{i}") for i in range(len(values))]
        # A row comparison - (a, b) > (x, y) - even for one column, where it is just
        # a > x. One code path, whatever the sort.
        return sql.SQL("({columns}) {operator} ({values})").format(
            columns=sql.SQL(", ").join(self._columns(table)),
            operator=sql.SQL(operator),
            values=sql.SQL(", ").join(placeholders),
        )

    def order_by(self, table: str | None = None) -> sql.Composable:
        direction = sql.SQL("ASC" if self.order == "asc" else "DESC")
        return sql.SQL(", ").join(
            sql.SQL("{column} {direction}").format(column=c, direction=direction)
            for c in self._columns(table)
        )

    def params(self) -> dict:
        """The parameters after_cursor() and the LIMIT need. Fetches one row more than
        the page holds - see build_page."""
        values = self._cursor_values() or ()
        return {"limit": self.limit + 1, **{f"cursor_{i}": v for i, v in enumerate(values)}}


def build_page(rows: list, params: PageParams, to_item, page_class: type[Page] = Page) -> Page:
    """Turn `limit + 1` fetched rows into a page.

    Fetching one row more than asked for is how we know whether a next page exists,
    without a second COUNT(*) query: if the extra row came back, there is more.
    The next cursor holds the last row's sort values - every column of the sort.
    """
    has_more = len(rows) > params.limit
    rows = rows[: params.limit]
    items = [to_item(row) for row in rows]
    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = encode(params.sort, params.order, tuple(last[c] for c in SORTS[params.sort]))
    return page_class(items=items, next_cursor=next_cursor)
