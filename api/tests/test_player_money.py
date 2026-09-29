"""A player's balance, transactions and bets."""

from tests.conftest import (
    FIXTURE_BETS,
    FIXTURE_TRANSACTIONS,
    PLAYER_WITH_MONEY,
    PLAYER_WITH_NOTHING,
    fixture_player,
)

MONEY = f"/v1/players/{PLAYER_WITH_MONEY}"
NOTHING = f"/v1/players/{PLAYER_WITH_NOTHING}"


def every_page(client, url, **params) -> list[dict]:
    items, cursor = [], None
    while True:
        body = client.get(url, params={**params, **({"cursor": cursor} if cursor else {})}).json()
        items += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return items


# ------------------------------------------------------------------- balance

def test_balance_adds_up(client):
    body = client.get(f"{MONEY}/balance").json()

    assert body == {
        "player_id": PLAYER_WITH_MONEY,
        "currency": fixture_player(PLAYER_WITH_MONEY)["currency"],
        "balance": "105.00",
        "deposited": "150.00",    # the rejected 30.00 does not count
        "withdrawn": "50.00",     # the pending 10.00 does - it is already reserved
        "staked": "40.00",        # the open bet's 5.00 too
        "paid_out": "45.00",
    }


def test_balance_of_a_player_with_nothing_is_zero_with_two_decimals(client):
    body = client.get(f"{NOTHING}/balance").json()

    assert body["balance"] == body["deposited"] == body["staked"] == "0.00"


def test_unknown_player_is_404_on_every_sub_resource(client):
    for sub in ("balance", "transactions", "bets"):
        response = client.get(f"/v1/players/999999/{sub}")
        assert response.status_code == 404, sub
        assert response.json()["detail"] == "Player 999999 does not exist."


# -------------------------------------------------------------- transactions

def test_transactions_in_order_with_the_method_nested(client):
    items = every_page(client, f"{MONEY}/transactions")

    assert [(t["direction"], t["amount"], t["status"]) for t in items] == [
        (d, a, s) for d, a, s, _, _ in FIXTURE_TRANSACTIONS
    ]
    assert items[0]["method"] == {"id": items[0]["method"]["id"], "type": "card", "last4": "4242"}


def test_the_fingerprint_never_leaves_the_api(client):
    response = client.get(f"{MONEY}/transactions")

    assert "fingerprint" not in response.text
    assert "ab" * 32 not in response.text


def test_pending_transaction_has_no_processed_at(client):
    items = every_page(client, f"{MONEY}/transactions", status="pending")

    assert len(items) == 1
    assert items[0]["processed_at"] is None


def test_transactions_paginate(client):
    pages = []
    cursor = None
    while True:
        body = client.get(f"{MONEY}/transactions", params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        pages.append(len(body["items"]))
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == [2, 2, 1]


def test_transaction_filters(client):
    assert len(every_page(client, f"{MONEY}/transactions", direction="deposit")) == 3
    assert len(every_page(client, f"{MONEY}/transactions", status="approved")) == 3
    assert len(every_page(client, f"{MONEY}/transactions", since="2026-08-04T12:00:00Z")) == 2


def test_transactions_since_needs_a_timezone(client):
    response = client.get(f"{MONEY}/transactions", params={"since": "2026-08-04T12:00:00"})

    assert response.status_code == 422


def test_player_with_no_transactions_gets_an_empty_page_not_a_404(client):
    body = client.get(f"{NOTHING}/transactions").json()

    assert body == {"items": [], "next_cursor": None}


# ---------------------------------------------------------------------- bets

def test_bets_with_their_settlement(client):
    items = every_page(client, f"{MONEY}/bets")

    assert [(b["stake"], b["status"], b["payout"]) for b in items] == [
        ("20.00", "won", "45.00"),
        ("15.00", "lost", "0.00"),
        ("5.00", "open", None),        # not settled yet
    ]
    assert items[2]["settled_at"] is None
    assert items[0]["total_odds"] == FIXTURE_BETS[0][1]


def test_bet_status_filter(client):
    items = every_page(client, f"{MONEY}/bets", status="won")

    assert [b["payout"] for b in items] == ["45.00"]


def test_money_is_always_a_string_with_two_decimals(client):
    items = every_page(client, f"{MONEY}/transactions") + every_page(client, f"{MONEY}/bets")
    amounts = [i.get("amount") or i.get("stake") for i in items]

    assert all(isinstance(a, str) and len(a.split(".")[1]) == 2 for a in amounts), amounts


def test_a_bet_settled_twice_still_appears_once(client):
    # Why the query uses LEFT JOIN LATERAL ... LIMIT 1: the schema allows two
    # settlement rows for one bet, and a plain LEFT JOIN would then return the bet
    # twice - a duplicated row that breaks cursor pagination.
    import psycopg

    from tests.conftest import TEST_DATABASE_URL, at

    first_bet_id = every_page(client, f"{MONEY}/bets")[0]["id"]
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        extra = conn.execute(
            "INSERT INTO settlements (bet_id, result, payout, settled_at) "
            "VALUES (%s, 'won', 45.00, %s) RETURNING id",
            (first_bet_id, at(7, 14)),
        ).fetchone()[0]
    try:
        ids = [b["id"] for b in every_page(client, f"{MONEY}/bets")]
        assert ids.count(first_bet_id) == 1
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM settlements WHERE id = %s", (extra,))
