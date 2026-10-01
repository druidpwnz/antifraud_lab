"""order=asc|desc, and what a cursor remembers about it."""

import base64

import psycopg

from tests.conftest import PLAYER_COUNT, TEST_DATABASE_URL, fixture_player


def ids(client, url="/v1/players", **params) -> list[int]:
    out, cursor = [], None
    while True:
        query = {**params, **({"cursor": cursor} if cursor else {})}
        body = client.get(url, params=query).json()
        out += [item["id"] for item in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            return out


def test_newest_first_covers_everything_exactly_once(client):
    assert ids(client, order="desc", limit=7) == list(range(PLAYER_COUNT, 0, -1))


def test_oldest_first_is_still_the_default(client):
    assert ids(client, limit=7) == ids(client, order="asc", limit=7) == list(range(1, PLAYER_COUNT + 1))


def test_order_combines_with_filters(client):
    expected = [n for n in range(PLAYER_COUNT, 0, -1) if fixture_player(n)["status"] == "active"]

    assert ids(client, order="desc", status="active", limit=4) == expected


def test_a_cursor_cannot_be_used_with_the_other_order(client):
    # "after id 20" means opposite things in the two directions; mixing them would
    # silently return the wrong rows.
    cursor = client.get("/v1/players", params={"order": "desc", "limit": 5}).json()["next_cursor"]

    response = client.get("/v1/players", params={"order": "asc", "cursor": cursor})

    assert response.status_code == 400
    assert response.json()["detail"] == "This cursor was made for order=desc; ask with the same order."


def test_a_cursor_from_before_order_existed_still_works(client):
    # Cursors used to be "id:<n>". A client half-way through paging when the format
    # changed must not break - one of the reasons cursors are opaque.
    old_style = base64.urlsafe_b64encode(b"id:10").decode().rstrip("=")

    body = client.get("/v1/players", params={"cursor": old_style, "limit": 3}).json()

    assert [p["id"] for p in body["items"]] == [11, 12, 13]


def test_unknown_order_is_422_and_unknown_cursor_order_is_400(client):
    assert client.get("/v1/players", params={"order": "sideways"}).status_code == 422
    forged = base64.urlsafe_b64encode(b"id:sideways:10").decode().rstrip("=")
    assert client.get("/v1/players", params={"cursor": forged}).status_code == 400


def test_newest_first_does_not_show_rows_created_after_you_started(client):
    # The flip side of asc: there, a new row turns up on a later page. Newest-first
    # started above every existing id, so a row created mid-way is above the start
    # and never appears - you see it by starting again from the top. Nothing is
    # skipped or repeated either way.
    first = client.get("/v1/players", params={"order": "desc", "limit": 10}).json()
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        new_id = conn.execute(
            "INSERT INTO players (registered_at, country, currency) "
            "VALUES (now(), 'ZZ', 'EUR') RETURNING id"
        ).fetchone()[0]
    try:
        rest = ids(client, order="desc", limit=10, cursor=first["next_cursor"])
        seen = [p["id"] for p in first["items"]] + rest

        assert new_id not in seen
        assert seen == list(range(PLAYER_COUNT, 0, -1))
        assert ids(client, order="desc", limit=10)[0] == new_id     # from the top: there it is
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM players WHERE id = %s", (new_id,))


def test_every_list_endpoint_accepts_order(client):
    for url in ("/v1/players", "/v1/players/1/transactions", "/v1/players/1/bets", "/v1/events", "/v1/bets"):
        asc = ids(client, url, limit=2)
        desc = ids(client, url, order="desc", limit=2)
        assert desc == list(reversed(asc)), url
