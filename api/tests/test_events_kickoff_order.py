"""GET /v1/events?sort=start_time: kickoff order, and the two-column cursor."""

import base64
from contextlib import contextmanager

import psycopg

from tests.conftest import TEST_DATABASE_URL, at


@contextmanager
def extra_events(*kickoffs):
    """Insert matches at these kickoff times for one test, and remove them after."""
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        ids = [conn.execute(
            "INSERT INTO events (sport, league, home_team, away_team, start_time) "
            "VALUES ('football', 'Test League', %s, %s, %s) RETURNING id",
            (f"Home {n}", f"Away {n}", kickoff),
        ).fetchone()[0] for n, kickoff in enumerate(kickoffs)]
    try:
        yield ids
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM events WHERE id = ANY(%s)", (ids,))


def walk(client, **params) -> list[int]:
    """Every event id, one page at a time, following next_cursor."""
    out, cursor = [], None
    while True:
        body = client.get("/v1/events", params={**params, **({"cursor": cursor} if cursor else {})}).json()
        out += [e["id"] for e in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            return out


def test_kickoff_order_is_not_id_order(client):
    # an event created last, kicking off first
    with extra_events(at(1, 9)) as (early,):
        assert walk(client, sort="start_time")[0] == early
        assert walk(client)[-1] == early                       # id order: it is last


def test_matches_sharing_a_kickoff_are_neither_skipped_nor_repeated(client):
    # Why the cursor carries the id as well as the time. Four matches at 15:00,
    # fetched ONE per page: a cursor holding only "after 15:00" would jump straight
    # past the other three.
    with extra_events(at(20, 15), at(20, 15), at(20, 15), at(20, 15)) as tied:
        seen = walk(client, sort="start_time", limit=1)

        assert seen.count(tied[0]) == 1
        assert [i for i in seen if i in tied] == tied          # each once, ties in id order
        assert len(seen) == len(set(seen))


def test_kickoff_order_backwards_with_ties(client):
    with extra_events(at(20, 15), at(20, 15), at(20, 15)) as tied:
        backwards = walk(client, sort="start_time", order="desc", limit=1)

        assert backwards == list(reversed(walk(client, sort="start_time", limit=1)))
        assert backwards[:3] == list(reversed(tied))           # latest kickoff first


def test_kickoff_order_combines_with_filters_and_windows(client):
    # the panel's "upcoming matches": scheduled, kicking off after some moment, soonest first
    ids = walk(client, sort="start_time", status="scheduled", **{"from": "2026-08-10T00:00:00Z"})

    assert ids == [2, 3]


def test_a_cursor_belongs_to_one_sort(client):
    by_id = client.get("/v1/events", params={"limit": 1}).json()["next_cursor"]
    by_time = client.get("/v1/events", params={"limit": 1, "sort": "start_time"}).json()["next_cursor"]

    wrong_sort = client.get("/v1/events", params={"sort": "start_time", "cursor": by_id})
    assert wrong_sort.status_code == 400
    assert wrong_sort.json()["detail"] == "This cursor was made for sort=id; ask with the same sort."

    # and a kickoff cursor is meaningless anywhere that only sorts by id
    assert client.get("/v1/players", params={"cursor": by_time}).status_code == 400


def test_forged_cursors_are_400(client):
    def forge(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    for raw in (
        b"start_time:asc:2026-08-10T15:00:00|2",          # no time zone
        b"start_time:asc:not-a-time|2",
        b"start_time:asc:2026-08-10T15:00:00+00:00",      # missing the id
        b"start_time:asc:2026-08-10T15:00:00+00:00|2|3",  # one value too many
    ):
        response = client.get("/v1/events", params={"sort": "start_time", "cursor": forge(raw)})
        assert response.status_code == 400, raw


def test_unknown_sort_is_422(client):
    assert client.get("/v1/events", params={"sort": "home_team"}).status_code == 422


def test_sort_is_documented(client):
    params = client.get("/openapi.json").json()["paths"]["/v1/events"]["get"]["parameters"]
    sort = next(p for p in params if p["name"] == "sort")

    assert sort["schema"]["enum"] == ["id", "start_time"]
