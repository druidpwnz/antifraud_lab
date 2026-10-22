"""Prometheus metrics: counted by route template, never by a raw path.

The counters live in one registry for the whole test run, so every test compares
before and after instead of expecting an absolute number.
"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app import errors, metrics
from tests.conftest import PLAYER_WITH_MONEY, PLAYER_WITH_NOTHING, fixture_player

PLAYER_ROUTE = "/v1/players/{player_id}"


def requests(route, status, method="GET"):
    value = REGISTRY.get_sample_value(
        "api_requests_total", {"method": method, "route": route, "status": str(status)}
    )
    return value or 0.0


def timed(route, method="GET"):
    value = REGISTRY.get_sample_value(
        "api_request_duration_seconds_count", {"method": method, "route": route}
    )
    return value or 0.0


def decisions(decision):
    return REGISTRY.get_sample_value("api_risk_decisions_total", {"decision": decision})


def route_labels():
    return {
        sample.labels["route"]
        for family in REGISTRY.collect() if family.name == "api_requests"
        for sample in family.samples if "route" in sample.labels
    }


def test_two_players_are_one_series_under_the_route_template(client):
    before = requests(PLAYER_ROUTE, 200)
    client.get(f"/v1/players/{PLAYER_WITH_MONEY}")
    client.get(f"/v1/players/{PLAYER_WITH_NOTHING}")
    assert requests(PLAYER_ROUTE, 200) - before == 2
    assert requests(f"/v1/players/{PLAYER_WITH_MONEY}", 200) == 0


def test_the_status_code_is_a_label_and_the_time_is_measured(client):
    not_found, timed_before = requests(PLAYER_ROUTE, 404), timed(PLAYER_ROUTE)
    client.get("/v1/players/999999")
    assert requests(PLAYER_ROUTE, 404) - not_found == 1
    assert timed(PLAYER_ROUTE) - timed_before == 1


def test_a_request_without_a_key_is_counted_as_401_on_its_route(client):
    before = requests(PLAYER_ROUTE, 401)
    client.get(f"/v1/players/{PLAYER_WITH_MONEY}", headers={"X-API-Key": ""})
    assert requests(PLAYER_ROUTE, 401) - before == 1


def test_an_unknown_path_is_one_label_whatever_the_path(client):
    before = requests(metrics.UNMATCHED, 404)
    client.get("/wp-admin/setup.php")
    client.get(f"/no/such/thing/{uuid.uuid4()}")
    assert requests(metrics.UNMATCHED, 404) - before == 2


def test_no_route_label_ever_holds_an_id(client):
    client.get(f"/v1/players/{PLAYER_WITH_MONEY}/bets")
    client.get("/v1/bets/1")
    client.get("/v1/events/1")
    client.get("/v1/does-not-exist/12345")
    labels = route_labels()
    assert labels, "no requests were counted at all"
    assert not [label for label in labels if any(ch.isdigit() for ch in label.replace("v1", ""))]


def test_a_new_risk_check_counts_its_decision_and_a_replay_does_not(client):
    key = str(uuid.uuid4())
    body = {"player_id": PLAYER_WITH_MONEY, "direction": "deposit", "amount": "20.00",
            "currency": fixture_player(PLAYER_WITH_MONEY)["currency"]}
    before = decisions("approve")
    first = client.post("/v1/risk-checks", json=body, headers={"Idempotency-Key": key})
    replay = client.post("/v1/risk-checks", json=body, headers={"Idempotency-Key": key})
    assert (first.status_code, replay.status_code) == (201, 200)
    assert first.json()["decision"] == "approve"
    assert decisions("approve") - before == 1


def test_every_decision_exists_before_any_was_made():
    # a counter that was never touched has no series at all - an alert on
    # "no declines today" would see no data instead of a 0
    for decision in ("approve", "review", "decline"):
        assert decisions(decision) is not None


def test_a_crash_is_counted_as_a_500():
    app = FastAPI()
    errors.install(app)
    app.add_middleware(metrics.MetricsMiddleware)

    @app.get("/boom/{thing_id}")
    def boom(thing_id: int):
        raise RuntimeError("on purpose")

    before = requests("/boom/{thing_id}", 500)
    response = TestClient(app, raise_server_exceptions=False).get("/boom/7")
    assert response.status_code == 500
    assert requests("/boom/{thing_id}", 500) - before == 1
