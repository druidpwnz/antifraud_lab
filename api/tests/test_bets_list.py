"""GET /v1/bets: bets across every player."""

from tests.conftest import FIXTURE_BETS, PLAYER_WITH_MONEY, READ_KEY


def bets(client, **params) -> list[dict]:
    return client.get("/v1/bets", params={"limit": 100, **params}).json()["items"]


def test_lists_every_bet_with_its_player(client):
    items = bets(client)

    assert [b["id"] for b in items] == [1, 2, 3]
    assert {b["player_id"] for b in items} == {PLAYER_WITH_MONEY}
    assert [b["stake"] for b in items] == [stake for stake, *_ in FIXTURE_BETS]


def test_newest_first(client):
    assert [b["id"] for b in bets(client, order="desc")] == [3, 2, 1]


def test_filters(client):
    assert [b["id"] for b in bets(client, status="won")] == [1]
    assert [b["id"] for b in bets(client, min_stake="15.00")] == [1, 2]       # 20.00 and 15.00, not 5.00
    assert [b["id"] for b in bets(client, placed_after="2026-08-08T00:00:00Z")] == [2, 3]


def test_settlement_is_included(client):
    by_id = {b["id"]: b for b in bets(client)}

    assert by_id[1]["payout"] == "45.00"
    assert by_id[3]["payout"] is None


def test_bad_filters_are_422(client):
    assert client.get("/v1/bets", params={"min_stake": "-1"}).status_code == 422
    assert client.get("/v1/bets", params={"min_stake": "1.005"}).status_code == 422
    assert client.get("/v1/bets", params={"placed_after": "2026-08-08T00:00:00"}).status_code == 422
    assert client.get("/v1/bets", params={"status": "banana"}).status_code == 422


def test_the_admin_panels_read_key_can_list_bets(client):
    assert client.get("/v1/bets", headers={"X-API-Key": READ_KEY}).status_code == 200


def test_bet_detail_still_works_next_to_the_list(client):
    # "/bets" and "/bets/{id}" on the same router: the list must not swallow the detail
    assert client.get("/v1/bets/1").json()["legs"]
