from datetime import datetime

import psycopg

from tests.conftest import PLAYER_COUNT, TEST_DATABASE_URL, fixture_player


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------ one player

def test_get_player(client):
    response = client.get("/v1/players/3")

    assert response.status_code == 200
    expected = fixture_player(3)
    assert response.json() == {**expected, "registered_at": iso(expected["registered_at"])}


def test_timestamps_are_utc_with_a_z(client):
    registered_at = client.get("/v1/players/1").json()["registered_at"]

    assert registered_at.endswith("Z")


def test_unknown_player_is_404_problem(client):
    response = client.get("/v1/players/999999")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "Player 999999 does not exist."


def test_player_id_must_be_positive(client):
    assert client.get("/v1/players/0").status_code == 422
    assert client.get("/v1/players/abc").status_code == 422


def test_players_need_a_key(client):
    response = client.get("/v1/players/1", headers={"X-API-Key": "wrong"})

    assert response.status_code == 401


# ---------------------------------------------------------------- pagination

def collect_ids(client, **params) -> list[int]:
    """Walk every page, following next_cursor until it runs out."""
    ids, cursor = [], None
    while True:
        query = {**params, **({"cursor": cursor} if cursor else {})}
        body = client.get("/v1/players", params=query).json()
        ids += [p["id"] for p in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            return ids


def test_pages_cover_everything_exactly_once_in_order(client):
    ids = collect_ids(client, limit=10)

    assert ids == list(range(1, PLAYER_COUNT + 1))


def test_page_sizes_and_the_last_page(client):
    first = client.get("/v1/players", params={"limit": 10}).json()
    assert len(first["items"]) == 10
    assert first["next_cursor"] is not None

    everything = client.get("/v1/players", params={"limit": 100}).json()
    assert len(everything["items"]) == PLAYER_COUNT
    assert everything["next_cursor"] is None


def test_exactly_full_last_page_has_no_next_cursor(client):
    # 25 players in pages of 25: the "limit + 1" trick must not promise a page 2.
    body = client.get("/v1/players", params={"limit": PLAYER_COUNT}).json()

    assert len(body["items"]) == PLAYER_COUNT
    assert body["next_cursor"] is None


def test_rows_inserted_while_paging_are_neither_skipped_nor_repeated(client):
    # The whole point of cursors over offsets. Take page 1, insert a player, carry on.
    first = client.get("/v1/players", params={"limit": 10}).json()
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        new_id = conn.execute(
            "INSERT INTO players (registered_at, country, currency) "
            "VALUES (now(), 'ZZ', 'EUR') RETURNING id"
        ).fetchone()[0]
    try:
        rest = collect_ids(client, limit=10, cursor=first["next_cursor"])
        seen = [p["id"] for p in first["items"]] + rest

        assert len(seen) == len(set(seen)), "a player appeared twice"
        assert set(range(1, PLAYER_COUNT + 1)) <= set(seen), "a player was skipped"
        assert seen[-1] == new_id, "the new player should turn up at the end"
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM players WHERE id = %s", (new_id,))


def test_limit_outside_1_to_100_is_422(client):
    assert client.get("/v1/players", params={"limit": 0}).status_code == 422
    assert client.get("/v1/players", params={"limit": 101}).status_code == 422


def test_garbage_cursor_is_400(client):
    for cursor in ["not-a-cursor", "aWQ6LTE", "Zm9vOjEy", "!!!"]:   # junk, id:-1, foo:12, junk
        response = client.get("/v1/players", params={"cursor": cursor})
        assert response.status_code == 400, cursor
        assert response.json()["detail"] == "Invalid cursor."


# ------------------------------------------------------------------- filters

def test_filter_by_country(client):
    ids = collect_ids(client, country="UA")

    assert ids == [n for n in range(1, PLAYER_COUNT + 1) if fixture_player(n)["country"] == "UA"]


def test_filter_by_status(client):
    ids = collect_ids(client, status="suspended")

    assert ids == [7, 14]


def test_filters_combine_with_pagination(client):
    ids = collect_ids(client, status="active", limit=3)

    assert ids == [n for n in range(1, PLAYER_COUNT + 1) if fixture_player(n)["status"] == "active"]


def test_registered_after(client):
    after = fixture_player(20)["registered_at"]

    ids = collect_ids(client, registered_after=iso(after))

    assert ids == list(range(21, PLAYER_COUNT + 1))


def test_registered_after_without_a_timezone_is_422(client):
    response = client.get("/v1/players", params={"registered_after": "2026-08-01T12:00:00"})

    assert response.status_code == 422


def test_bad_filter_values_are_422(client):
    assert client.get("/v1/players", params={"country": "ukr"}).status_code == 422
    assert client.get("/v1/players", params={"status": "banana"}).status_code == 422
