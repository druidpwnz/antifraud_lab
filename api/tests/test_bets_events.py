"""One bet with its legs; events with their markets and selections."""

from decimal import Decimal

from tests.conftest import FIXTURE_BETS, FIXTURE_EVENTS

# Fixture rows are inserted in order into freshly truncated tables, so ids are 1, 2, 3.
WON_SINGLE, LOST_SINGLE, OPEN_COMBO = 1, 2, 3
FINISHED_MATCH, REAL_BARCA, BAYERN_BVB = 1, 2, 3


def event_ids(client, **params) -> list[int]:
    return [e["id"] for e in client.get("/v1/events", params={"limit": 100, **params}).json()["items"]]


# ----------------------------------------------------------------- bet detail

def test_won_single_with_its_leg_and_settlement(client):
    bet = client.get(f"/v1/bets/{WON_SINGLE}").json()

    assert bet["status"] == "won"
    assert bet["total_odds"] == "2.250"
    (leg,) = bet["legs"]
    assert leg["outcome"] == "home"
    assert leg["name"] == "Arsenal"
    assert leg["odds_at_placement"] == "2.25"
    assert leg["selection_status"] == "won"
    assert leg["market"] == {"id": leg["market"]["id"], "type": "1x2", "line": "0.00"}
    assert leg["event"]["home_team"] == "Arsenal"
    assert leg["event"]["status"] == "finished"
    assert bet["settlement"]["result"] == "won"
    assert bet["settlement"]["payout"] == "45.00"


def test_combo_legs_are_in_kickoff_order_and_multiply_to_total_odds(client):
    bet = client.get(f"/v1/bets/{OPEN_COMBO}").json()

    assert [leg["event"]["home_team"] for leg in bet["legs"]] == ["Real Madrid", "Bayern Munich"]
    product = Decimal(1)
    for leg in bet["legs"]:
        product *= Decimal(leg["odds_at_placement"])
    assert product.quantize(Decimal("0.001")) == Decimal(bet["total_odds"]) == Decimal(FIXTURE_BETS[2][1])


def test_open_bet_has_no_settlement(client):
    assert client.get(f"/v1/bets/{OPEN_COMBO}").json()["settlement"] is None


def test_a_bet_keeps_its_price_after_the_market_moves(client):
    # Bet 3 took Real Madrid at 1.55; the selection is at 1.50 now.
    leg = client.get(f"/v1/bets/{OPEN_COMBO}").json()["legs"][0]
    market = client.get(f"/v1/events/{REAL_BARCA}").json()["markets"][0]
    home = next(s for s in market["selections"] if s["outcome"] == "home")

    assert leg["odds_at_placement"] == "1.55"
    assert home["current_odds"] == "1.50"


def test_unknown_bet_is_404_and_bad_id_is_422(client):
    response = client.get("/v1/bets/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Bet 999999 does not exist."

    assert client.get("/v1/bets/0").status_code == 422


# ---------------------------------------------------------------- event list

def test_events_list_and_filters(client):
    assert event_ids(client) == [FINISHED_MATCH, REAL_BARCA, BAYERN_BVB]
    assert event_ids(client, status="scheduled") == [REAL_BARCA, BAYERN_BVB]
    assert event_ids(client, league="La Liga") == [REAL_BARCA]


def test_kickoff_window(client):
    assert event_ids(client, **{"from": "2026-08-10T00:00:00Z", "to": "2026-08-11T00:00:00Z"}) == [REAL_BARCA]


def test_kickoff_window_is_half_open(client):
    # Real Madrid - Barcelona kicks off at exactly 2026-08-10 19:00.
    kickoff = "2026-08-10T19:00:00Z"

    assert REAL_BARCA in event_ids(client, **{"from": kickoff})      # from is inclusive
    assert REAL_BARCA not in event_ids(client, **{"to": kickoff})    # to is exclusive


def test_from_must_be_before_to(client):
    response = client.get("/v1/events", params={"from": "2026-08-11T00:00:00Z", "to": "2026-08-10T00:00:00Z"})

    assert response.status_code == 422
    assert response.json()["detail"] == "`from` must be earlier than `to`."


def test_window_needs_a_timezone(client):
    assert client.get("/v1/events", params={"from": "2026-08-10T00:00:00"}).status_code == 422


def test_the_public_parameter_is_called_from_not_starts_from(client):
    params = client.get("/openapi.json").json()["paths"]["/v1/events"]["get"]["parameters"]
    names = {p["name"] for p in params}

    assert {"from", "to"} <= names
    assert "starts_from" not in names


# -------------------------------------------------------------- event detail

def test_event_with_its_markets_and_selections(client):
    event = client.get(f"/v1/events/{FINISHED_MATCH}").json()
    expected = FIXTURE_EVENTS[0]

    assert event["home_team"] == expected["home_team"]
    assert [m["type"] for m in event["markets"]] == ["1x2", "total_goals"]
    assert [m["line"] for m in event["markets"]] == ["0.00", "2.50"]
    one_x_two = event["markets"][0]
    assert [(s["outcome"], s["current_odds"], s["status"]) for s in one_x_two["selections"]] == [
        (o, odds, status) for o, _, odds, status in expected["markets"][0][3]
    ]


def test_unknown_event_is_404(client):
    response = client.get("/v1/events/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Event 999999 does not exist."
