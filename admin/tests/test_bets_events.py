"""Bets and events: the lists, one bet, one match."""

import copy
from urllib.parse import parse_qs

import pytest

from app.views.bets import warnings_for

HTMX = {"HX-Request": "true"}

SUMMARY = {"id": 900, "player_id": 5, "placed_at": "2026-08-19T11:00:00Z", "stake": "20.00",
           "currency": "PLN", "total_odds": "2.150", "status": "won", "payout": "43.00",
           "settled_at": "2026-08-19T13:00:00Z"}
EVENT = {"id": 482, "sport": "football", "league": "Ekstraklasa", "home_team": "Legia Warszawa",
         "away_team": "Lech Poznan", "start_time": "2026-08-19T15:00:00Z", "status": "finished",
         "finished_at": "2026-08-19T16:55:00Z"}
BET = {
    "id": 900, "player_id": 5, "placed_at": "2026-08-19T11:00:00Z", "stake": "20.00",
    "currency": "PLN", "total_odds": "2.150", "status": "won",
    "legs": [{
        "selection_id": 7, "outcome": "home", "name": "Legia Warszawa",
        "odds_at_placement": "2.150", "selection_status": "won",
        "market": {"id": 3, "type": "1x2", "line": "0.00"},
        "event": {k: EVENT[k] for k in ("id", "league", "home_team", "away_team", "start_time", "status")},
    }],
    "settlement": {"result": "won", "payout": "43.00", "settled_at": "2026-08-19T17:00:00Z"},
}
EVENT_DETAIL = {**EVENT, "markets": [
    {"id": 3, "type": "1x2", "line": "0.00", "status": "settled", "selections": [
        {"id": 7, "outcome": "home", "name": "Legia Warszawa", "current_odds": "2.150", "status": "won"},
        {"id": 8, "outcome": "draw", "name": "Draw", "current_odds": "3.300", "status": "lost"},
    ]},
    {"id": 4, "type": "total_goals", "line": "2.50", "status": "settled", "selections": [
        {"id": 9, "outcome": "over", "name": "Over 2.5", "current_odds": "1.900", "status": "lost"},
    ]},
]}


def page(items, next_cursor=None):
    return (200, {"items": items, "next_cursor": next_cursor})


def bet(**changes):
    """BET with some fields changed. settlement=... and placed_at=... are the usual ones."""
    b = copy.deepcopy(BET)
    b.update(changes)
    return b


def query(client, path):
    (call,) = [r for r in client.transport.seen if r.url.path == path]
    return {k: v[0] for k, v in parse_qs(call.url.query.decode()).items()}


# ------------------------------------------------------------------ bets list

def test_bets_list_page(make_client):
    client = make_client({"/v1/bets": page([SUMMARY])})
    html = client.get("/bets").get_data(as_text=True)
    assert "<html" in html and 'id="bet-rows"' in html
    assert 'href="/bets/900"' in html and 'href="/players/5"' in html
    assert "20.00 PLN" in html and "43.00 PLN" in html
    assert query(client, "/v1/bets") == {"order": "desc", "limit": "25"}


def test_bets_filters_go_to_the_api(make_client):
    client = make_client({"/v1/bets": page([])})
    client.get("/bets?status=lost&min_stake=500&order=asc&cursor=C")
    assert query(client, "/v1/bets") == {"status": "lost", "min_stake": "500", "order": "asc",
                                         "cursor": "C", "limit": "25"}


def test_bets_htmx_gets_rows_and_load_more_keeps_filters(make_client):
    client = make_client({"/v1/bets": page([SUMMARY], next_cursor="N")})
    html = client.get("/bets?status=won&min_stake=10", headers=HTMX).get_data(as_text=True)
    assert "<table" not in html
    assert 'hx-get="/bets?cursor=N&amp;status=won&amp;min_stake=10&amp;order=desc"' in html


@pytest.mark.parametrize("typed", ["abc", "-1", "1.234", "1e3", "NaN", "Infinity", "5."])
def test_bad_min_stake_is_a_400_without_asking_the_api(make_client, typed):
    client = make_client({"/v1/bets": page([])})
    response = client.get("/bets", query_string={"min_stake": typed})
    assert response.status_code == 400
    assert "Minimum stake is an amount" in response.get_data(as_text=True)
    assert not [r for r in client.transport.seen if r.url.path == "/v1/bets"]


@pytest.mark.parametrize("typed", ["0", "500", "12.5", "12.50", " 7 "])
def test_good_min_stake_is_accepted(make_client, typed):
    client = make_client({"/v1/bets": page([])})
    assert client.get("/bets", query_string={"min_stake": typed}).status_code == 200


def test_bets_empty_state(make_client):
    client = make_client({"/v1/bets": page([])})
    assert "No bets match these filters." in client.get("/bets").get_data(as_text=True)


def test_bets_go(make_client):
    client = make_client()
    assert client.get("/bets/go?id=%23900").headers["Location"] == "/bets/900"
    assert client.get("/bets/go?id=x").status_code == 400


# ------------------------------------------------------------------ one bet

def test_bet_page(make_client):
    client = make_client({"/v1/bets/900": (200, BET)})
    html = client.get("/bets/900").get_data(as_text=True)
    assert "Bet #900" in html
    assert 'href="/players/5"' in html and 'href="/events/482"' in html
    assert "Legia Warszawa – Lech Poznan" in html
    assert "Match result" in html                     # 1x2, named
    assert "43.00 PLN" in html
    assert "warnings" not in html                     # a clean bet has none


def test_unsettled_bet(make_client):
    client = make_client({"/v1/bets/900": (200, bet(status="open", settlement=None))})
    html = client.get("/bets/900").get_data(as_text=True)
    assert "Not settled" in html


def test_unknown_bet_is_a_404(make_client):
    client = make_client({"/v1/bets/1": (404, {"detail": "Bet 1 does not exist."})})
    response = client.get("/bets/1")
    assert response.status_code == 404
    assert "Bet 1 does not exist." in response.get_data(as_text=True)


def test_warning_is_shown_on_the_page(make_client):
    late = bet(placed_at="2026-08-19T15:20:00Z")
    client = make_client({"/v1/bets/900": (200, late)})
    html = client.get("/bets/900").get_data(as_text=True)
    assert "Placed after kickoff of Legia Warszawa – Lech Poznan." in html


def test_no_warnings_on_a_correct_bet():
    assert warnings_for(BET) == []


def test_late_bet_warning():
    # one second after kickoff - and with fractional seconds, which compare wrongly
    # as strings ("15:00:00.5Z" < "15:00:00Z")
    assert warnings_for(bet(placed_at="2026-08-19T15:00:00.5Z")) != []
    assert warnings_for(bet(placed_at="2026-08-19T14:59:59Z")) == []


def test_lost_but_paid_warning():
    paid = bet(status="lost", settlement={"result": "lost", "payout": "30.00",
                                          "settled_at": "2026-08-19T17:00:00Z"})
    assert warnings_for(paid) == ["Settled as lost, but paid out."]
    unpaid = bet(status="lost", settlement={"result": "lost", "payout": "0.00",
                                            "settled_at": "2026-08-19T17:00:00Z"})
    assert warnings_for(unpaid) == []


@pytest.mark.parametrize("payout,warned", [("43.00", False), ("43.01", False), ("43.05", True), ("40.00", True)])
def test_wrong_amount_warning(payout, warned):
    b = bet(settlement={"result": "won", "payout": payout, "settled_at": "2026-08-19T17:00:00Z"})
    assert bool(warnings_for(b)) is warned


# ------------------------------------------------------------------ events

def test_events_default_to_upcoming_in_kickoff_order(make_client):
    client = make_client({"/v1/events": page([EVENT])})
    html = client.get("/events").get_data(as_text=True)
    assert query(client, "/v1/events") == {"sort": "start_time", "status": "scheduled",
                                           "order": "asc", "limit": "25"}
    assert 'href="/events/482"' in html
    assert '<option value="scheduled" selected>Upcoming</option>' in html


def test_events_any_status_sends_no_status(make_client):
    client = make_client({"/v1/events": page([])})
    client.get("/events?status=&league=La+Liga&order=desc")
    assert query(client, "/v1/events") == {"sort": "start_time", "league": "La Liga",
                                           "order": "desc", "limit": "25"}


def test_events_load_more_keeps_any_status(make_client):
    # "Any" is status="" - it must survive into the load-more URL, or the next page
    # would quietly fall back to the default, Upcoming
    client = make_client({"/v1/events": page([EVENT], next_cursor="K")})
    html = client.get("/events?status=", headers=HTMX).get_data(as_text=True)
    assert "status=&amp;" in html


def test_unknown_event_status_falls_back_to_upcoming(make_client):
    client = make_client({"/v1/events": page([])})
    client.get("/events?status=exploded")
    assert query(client, "/v1/events")["status"] == "scheduled"


def test_event_page(make_client):
    client = make_client({"/v1/events/482": (200, EVENT_DETAIL)})
    html = client.get("/events/482").get_data(as_text=True)
    assert "Legia Warszawa – Lech Poznan" in html
    assert "Match result" in html and "Total goals" in html
    assert "3.300" in html and "Over 2.5" in html


def test_unknown_event_is_a_404(make_client):
    client = make_client({"/v1/events/9": (404, {"detail": "Event 9 does not exist."})})
    assert client.get("/events/9").status_code == 404


# ------------------------------------------------------------------ links between pages

def test_player_bets_tab_links_to_the_bet(make_client):
    player = {"id": 5, "registered_at": "2026-08-18T19:42:07Z", "country": "PL",
              "currency": "PLN", "status": "active"}
    client = make_client({"/v1/players/5": (200, player),
                          "/v1/players/5/balance": (200, {"player_id": 5, "currency": "PLN",
                              "balance": "0.00", "deposited": "0.00", "withdrawn": "0.00",
                              "staked": "0.00", "paid_out": "0.00"}),
                          "/v1/players/5/bets": page([SUMMARY])})
    assert 'href="/bets/900"' in client.get("/players/5?tab=bets").get_data(as_text=True)


@pytest.mark.parametrize("path,routes", [
    ("/bets", {"/v1/bets": page([])}),
    ("/bets/900", {"/v1/bets/900": (200, BET)}),
    ("/events", {"/v1/events": page([])}),
    ("/events/482", {"/v1/events/482": (200, EVENT_DETAIL)}),
])
def test_section_is_active_in_the_nav(make_client, path, routes):
    html = make_client(routes).get(path).get_data(as_text=True)
    section = path.split("/")[1]
    assert f'href="/{section}" class="active"' in html


@pytest.mark.parametrize("path", ["/bets", "/bets/900", "/events", "/events/482"])
def test_needs_a_login(make_client, path):
    assert make_client(logged_in=False).get(path).status_code == 302


@pytest.mark.parametrize("path,routes", [
    ("/players", {"/v1/players": page([])}),
    ("/bets", {"/v1/bets": page([])}),
    ("/events", {"/v1/events": page([])}),
])
def test_filter_forms_trigger_once_per_change(make_client, path, routes):
    # Selects on change, text fields on Enter (submit) - never both, or Enter in the
    # stake box sends two requests. A selector with a space must be in brackets, or
    # htmx's trigger parser fails - only in the browser, so the test pins the string.
    html = make_client(routes).get(path).get_data(as_text=True)
    assert 'hx-trigger="change from:(.filters select), submit"' in html
