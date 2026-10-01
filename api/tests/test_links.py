"""A player's sessions, and the players linked to them by a device or a card."""

from tests.conftest import (
    FIXTURE_SESSIONS,
    LAPTOP,
    PLAYER_WITH_MONEY,
    PLAYER_WITH_NOTHING,
    READ_KEY,
    SHARED_CARD,
)


def items(client, url, **params) -> list[dict]:
    return client.get(url, params={"limit": 100, **params}).json()["items"]


# ------------------------------------------------------------------ sessions

def test_a_players_sessions(client):
    sessions = items(client, "/v1/players/1/sessions")

    expected = [(d, ip) for p, d, ip, _ in FIXTURE_SESSIONS if p == PLAYER_WITH_MONEY]
    assert [(s["device_id"], s["ip"]) for s in sessions] == expected
    assert sessions[0]["user_agent"] == "pytest"
    assert sessions[0]["ended_at"].endswith("Z")


def test_ip_is_a_plain_address_not_a_network(client):
    # inet can carry a netmask; host() makes sure "198.51.100.10/32" never reaches a client
    assert "/" not in items(client, "/v1/players/1/sessions")[0]["ip"]


def test_sessions_newest_first(client):
    ids = [s["id"] for s in items(client, "/v1/players/1/sessions", order="desc")]

    assert ids == sorted(ids, reverse=True)


def test_no_sessions_and_unknown_player(client):
    assert items(client, f"/v1/players/{PLAYER_WITH_NOTHING}/sessions") == []
    assert client.get("/v1/players/999999/sessions").status_code == 404


# -------------------------------------------------------------------- linked

def test_linked_players_and_what_they_share(client):
    linked = items(client, "/v1/players/1/linked")

    assert [(p["id"], p["shared_devices"], p["shared_payment_methods"]) for p in linked] == [
        (5, 1, 0),      # the laptop
        (6, 0, 1),      # the card
        (8, 1, 1),      # the phone and the card
    ]


def test_many_sessions_on_one_shared_device_count_once(client):
    # Both players have two sessions on the laptop. What keeps it at one is UNION
    # (not UNION ALL): it removes duplicate (player, kind, value) rows, whichever
    # player's sessions they came from. With UNION ALL this test reads 2.
    player_5 = next(p for p in items(client, "/v1/players/1/linked") if p["id"] == 5)

    assert player_5["shared_devices"] == 1


def test_links_work_both_ways(client):
    assert [p["id"] for p in items(client, "/v1/players/5/linked")] == [1]
    assert [p["id"] for p in items(client, "/v1/players/6/linked")] == [1, 8]    # 6 and 8 share the card too


def test_the_evidence_never_leaves_the_database(client):
    # The whole point of /linked: say THAT two players share a card, never WHICH card.
    response = client.get("/v1/players/1/linked")

    assert SHARED_CARD not in response.text
    assert LAPTOP not in response.text
    assert "fingerprint" not in response.text


def test_a_player_is_never_linked_to_themselves(client):
    assert PLAYER_WITH_MONEY not in [p["id"] for p in items(client, "/v1/players/1/linked")]


def test_no_links_and_unknown_player(client):
    assert items(client, f"/v1/players/{PLAYER_WITH_NOTHING}/linked") == []
    assert client.get("/v1/players/999999/linked").status_code == 404


def test_linked_paginates(client):
    first = client.get("/v1/players/1/linked", params={"limit": 2}).json()
    rest = client.get("/v1/players/1/linked", params={"limit": 2, "cursor": first["next_cursor"]}).json()

    assert [p["id"] for p in first["items"]] == [5, 6]
    assert [p["id"] for p in rest["items"]] == [8]
    assert rest["next_cursor"] is None


def test_the_admin_panels_read_key_can_investigate(client):
    for sub in ("sessions", "linked"):
        assert client.get(f"/v1/players/1/{sub}", headers={"X-API-Key": READ_KEY}).status_code == 200
