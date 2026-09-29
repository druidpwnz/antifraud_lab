"""POST /v1/risk-checks: idempotency, the rules on real rows, and validation."""

import uuid

import psycopg

from tests.conftest import (
    PASSTHROUGH_PLAYER,
    PLAYER_WITH_MONEY,
    SIM_NOW,
    SUSPENDED_PLAYER,
    TEST_DATABASE_URL,
    VELOCITY_PLAYER,
    fixture_player,
)


def check(client, key=None, **body):
    """POST a risk check. A fresh Idempotency-Key unless one is given."""
    headers = {"Idempotency-Key": key or str(uuid.uuid4())}
    return client.post("/v1/risk-checks", json=body, headers=headers)


def deposit(player_id, amount, **extra):
    return {"player_id": player_id, "direction": "deposit", "amount": amount,
            "currency": fixture_player(player_id)["currency"], **extra}


def withdrawal(player_id, amount):
    return {**deposit(player_id, amount), "direction": "withdrawal"}


def reason_codes(response) -> list[str]:
    return [r["code"] for r in response.json()["reasons"]]


# ---------------------------------------------------------------- happy path

def test_ordinary_deposit_is_approved_201_with_location(client):
    response = check(client, **deposit(PLAYER_WITH_MONEY, "50.00"))

    assert response.status_code == 201
    body = response.json()
    assert response.headers["location"] == f"/v1/risk-checks/{body['id']}"
    assert (body["decision"], body["score"], body["reasons"]) == ("approve", 0, [])
    assert body["amount"] == "50.00"
    assert body["sim_time_at_check"] == SIM_NOW.isoformat().replace("+00:00", "Z")


def test_the_stored_check_can_be_fetched(client):
    created = check(client, **deposit(PLAYER_WITH_MONEY, "50.00"))

    fetched = client.get(created.headers["location"])

    assert fetched.status_code == 200
    assert fetched.json() == created.json()


def test_unknown_risk_check_is_404(client):
    response = client.get("/v1/risk-checks/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Risk check 999999 does not exist."


# --------------------------------------------------------------- idempotency

def test_retry_with_the_same_key_returns_the_same_decision(client):
    key = str(uuid.uuid4())
    first = check(client, key, **deposit(PLAYER_WITH_MONEY, "50.00"))

    again = check(client, key, **deposit(PLAYER_WITH_MONEY, "50.00"))

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.headers["idempotent-replayed"] == "true"
    assert again.headers["location"] == first.headers["location"]
    assert again.json() == first.json()


def test_a_retry_is_answered_as_decided_then_not_as_things_are_now(client):
    key = str(uuid.uuid4())
    first = check(client, key, **deposit(PLAYER_WITH_MONEY, "600.00"))   # > 10x median 50
    assert first.json()["decision"] == "review"

    # the player's history changes: three 1000.00 deposits move the median from 50 to
    # 1000, so 600.00 is no longer far above usual
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        method = conn.execute("SELECT id FROM payment_methods WHERE player_id = %s LIMIT 1",
                              (PLAYER_WITH_MONEY,)).fetchone()[0]
        added = [conn.execute(
            "INSERT INTO transactions (player_id, method_id, direction, amount, currency, status, "
            "created_at, processed_at) VALUES (%s, %s, 'deposit', 1000, %s, 'approved', "
            "'2026-08-10T10:00Z', '2026-08-10T10:01Z') RETURNING id",
            (PLAYER_WITH_MONEY, method, fixture_player(PLAYER_WITH_MONEY)["currency"]),
        ).fetchone()[0] for _ in range(3)]
    try:
        # a fresh check would now approve; the retry must still say "review"
        assert check(client, **deposit(PLAYER_WITH_MONEY, "600.00")).json()["decision"] == "approve"
        assert check(client, key, **deposit(PLAYER_WITH_MONEY, "600.00")).json()["decision"] == "review"
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM transactions WHERE id = ANY(%s)", (added,))


def test_same_key_with_a_different_body_is_422(client):
    key = str(uuid.uuid4())
    check(client, key, **deposit(PLAYER_WITH_MONEY, "50.00"))

    response = check(client, key, **deposit(PLAYER_WITH_MONEY, "51.00"))

    assert response.status_code == 422
    assert "different request body" in response.json()["detail"]


def test_50_and_50_00_are_the_same_request(client):
    key = str(uuid.uuid4())
    check(client, key, **deposit(PLAYER_WITH_MONEY, "50"))

    response = check(client, key, **deposit(PLAYER_WITH_MONEY, "50.00"))

    assert response.status_code == 200      # a replay, not a 422


def test_losing_a_race_to_an_identical_request_is_answered_as_a_replay(client, monkeypatch):
    # Two identical requests can both get past the "have I seen this key?" check
    # before either has inserted. Simulate being the second one: the fast-path lookup
    # finds nothing, so the handler scores and INSERTs - and the UNIQUE constraint
    # makes ON CONFLICT DO NOTHING return no row.
    from app.routers import risk_checks

    key = str(uuid.uuid4())
    first = check(client, key, **deposit(PLAYER_WITH_MONEY, "50.00"))

    real_find = risk_checks.find_by_key
    calls = []

    def find_nothing_the_first_time(conn, k):
        calls.append(k)
        return None if len(calls) == 1 else real_find(conn, k)

    monkeypatch.setattr(risk_checks, "find_by_key", find_nothing_the_first_time)
    second = check(client, key, **deposit(PLAYER_WITH_MONEY, "50.00"))

    assert len(calls) == 2                  # fast path missed, then the conflict path read it
    assert second.status_code == 200
    assert second.json() == first.json()
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        stored = conn.execute("SELECT count(*) FROM risk_checks WHERE idempotency_key = %s", (key,))
        assert stored.fetchone()[0] == 1


def test_idempotency_key_is_required(client):
    response = client.post("/v1/risk-checks", json=deposit(PLAYER_WITH_MONEY, "50.00"))

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["header", "idempotency-key"]


# --------------------------------------------------------- the rules, on rows

def test_wrong_currency_is_declined(client):
    response = check(client, **{**deposit(PLAYER_WITH_MONEY, "50.00"), "currency": "XYZ"})

    assert response.json()["decision"] == "decline"
    assert reason_codes(response) == ["currency_mismatch"]


def test_withdrawal_above_the_balance_is_declined(client):
    # player 1's balance is 105.00 (see conftest)
    assert reason_codes(check(client, **withdrawal(PLAYER_WITH_MONEY, "105.01"))) == ["insufficient_funds"]
    assert "insufficient_funds" not in reason_codes(check(client, **withdrawal(PLAYER_WITH_MONEY, "105.00")))


def test_suspended_player_is_declined(client):
    response = check(client, **deposit(SUSPENDED_PLAYER, "10.00"))

    assert reason_codes(response) == ["player_not_active"]


def test_deposit_velocity(client):
    response = check(client, **deposit(VELOCITY_PLAYER, "20.00"))

    assert response.json()["decision"] == "review"
    assert reason_codes(response) == ["deposit_velocity"]


def test_passthrough(client):
    response = check(client, **withdrawal(PASSTHROUGH_PLAYER, "300.00"))

    assert response.json()["decision"] == "review"
    assert reason_codes(response) == ["passthrough"]


def test_unknown_player_is_404(client):
    response = check(client, **{**deposit(PLAYER_WITH_MONEY, "10.00"), "player_id": 999999})

    assert response.status_code == 404


def test_no_simulated_clock_is_503(client):
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        saved = conn.execute("DELETE FROM sim_state RETURNING sim_time, seed, days").fetchone()
    try:
        response = check(client, **deposit(PLAYER_WITH_MONEY, "10.00"))
        assert response.status_code == 503
        assert "simulation clock" in response.json()["detail"]
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("INSERT INTO sim_state (id, sim_time, seed, days) VALUES (1, %s, %s, %s)", saved)


# ---------------------------------------------------------------- validation

def test_bad_bodies_are_422(client):
    bad = [
        {**deposit(PLAYER_WITH_MONEY, "10.00"), "ammount": "10.00"},   # unknown field
        deposit(PLAYER_WITH_MONEY, "10.005"),                            # 3 decimals
        deposit(PLAYER_WITH_MONEY, "-5.00"),                             # not positive
        deposit(PLAYER_WITH_MONEY, "0"),
        {**deposit(PLAYER_WITH_MONEY, "10.00"), "currency": "pln"},      # not ISO 4217 shape
        {**deposit(PLAYER_WITH_MONEY, "10.00"), "direction": "refund"},
    ]
    for body in bad:
        assert check(client, **body).status_code == 422, body


# ------------------------------------------------- the API leaves generator data alone

def test_risk_checks_never_touch_the_generators_tables(client):
    tables = ["transactions", "bets", "settlements", "players", "payment_methods"]

    def counts():
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}

    before = counts()
    for amount in ("10.00", "600.00", "5000.00"):
        check(client, **deposit(PLAYER_WITH_MONEY, amount))
        check(client, **withdrawal(PLAYER_WITH_MONEY, amount))

    assert counts() == before
