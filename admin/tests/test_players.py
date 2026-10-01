"""Players: the list with filters and load-more, and the player page with its tabs."""

import re
from urllib.parse import parse_qs, urlsplit

import pytest

from app.formatting import money, when

HTMX = {"HX-Request": "true"}

PLAYER = {"id": 5, "registered_at": "2026-08-18T19:42:07Z", "country": "PL",
          "currency": "PLN", "status": "active"}
BALANCE = {"player_id": 5, "currency": "PLN", "balance": "1234567.10", "deposited": "2000000.00",
           "withdrawn": "500000.00", "staked": "300000.00", "paid_out": "34567.10"}
TRANSACTION = {"id": 71, "direction": "deposit", "amount": "250.00", "currency": "PLN",
               "status": "approved", "created_at": "2026-08-19T10:00:00Z",
               "processed_at": "2026-08-19T10:02:00Z",
               "method": {"id": 3, "type": "card", "last4": "4242"}}
BET = {"id": 900, "player_id": 5, "placed_at": "2026-08-19T11:00:00Z", "stake": "20.00",
       "currency": "PLN", "total_odds": "2.150", "status": "won", "payout": "43.00",
       "settled_at": "2026-08-19T13:00:00Z"}
SESSION = {"id": 1, "started_at": "2026-08-19T09:00:00Z", "ended_at": None, "ip": "203.0.113.42",
           "device_id": "5e6d9db3-2217-4f70-b646-9a1f5f7402f2",
           "user_agent": "<script>alert(1)</script>"}
LINKED = {"id": 77, "country": "UA", "status": "suspended", "registered_at": "2026-08-01T00:00:00Z",
          "shared_devices": 2, "shared_payment_methods": 0}


def page(items, next_cursor=None):
    return (200, {"items": items, "next_cursor": next_cursor})


def player_api(**tabs):
    """The API for player 5: profile, balance, and every tab (empty unless given)."""
    routes = {"/v1/players/5": (200, PLAYER), "/v1/players/5/balance": (200, BALANCE)}
    for tab in ("transactions", "bets", "sessions", "linked"):
        routes[f"/v1/players/5/{tab}"] = tabs.get(tab, page([]))
    return routes


def query_of(request) -> dict:
    return {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}


def calls_to(client, path):
    return [r for r in client.transport.seen if r.url.path == path]


# ------------------------------------------------------------------ the list

def test_list_is_a_full_page_with_filters_and_rows(make_client):
    client = make_client({"/v1/players": page([PLAYER])})
    html = client.get("/players").get_data(as_text=True)
    assert "<html" in html
    assert 'id="player-rows"' in html
    assert 'href="/players/5"' in html
    assert 'name="country"' in html and 'name="status"' in html


def test_htmx_list_request_gets_rows_only(make_client):
    client = make_client({"/v1/players": page([PLAYER])})
    html = client.get("/players?country=PL", headers=HTMX).get_data(as_text=True)
    assert "<html" not in html and "<table" not in html
    assert html.lstrip().startswith("<tr>")


def test_filters_and_cursor_go_to_the_api(make_client):
    client = make_client({"/v1/players": page([])})
    client.get("/players?country=PL&status=suspended&order=asc&cursor=abc")
    (call,) = calls_to(client, "/v1/players")
    assert query_of(call) == {"country": "PL", "status": "suspended", "order": "asc",
                              "cursor": "abc", "limit": "25"}


def test_empty_filters_are_not_sent(make_client):
    client = make_client({"/v1/players": page([])})
    client.get("/players?country=&status=")
    (call,) = calls_to(client, "/v1/players")
    assert query_of(call) == {"order": "desc", "limit": "25"}


def test_unknown_order_falls_back_to_newest_first(make_client):
    client = make_client({"/v1/players": page([])})
    client.get("/players?order=sideways")
    assert query_of(calls_to(client, "/v1/players")[0])["order"] == "desc"


def test_selected_filters_stay_selected(make_client):
    client = make_client({"/v1/players": page([])})
    html = client.get("/players?country=UA&status=closed").get_data(as_text=True)
    assert '<option value="UA" selected>' in html
    assert '<option value="closed" selected>' in html


def test_load_more_keeps_the_filters(make_client):
    client = make_client({"/v1/players": page([PLAYER], next_cursor="NEXT")})
    html = client.get("/players?country=PL&status=active", headers=HTMX).get_data(as_text=True)
    assert 'id="load-more-row"' in html
    more = html.split('hx-get="', 1)[1].split('"', 1)[0].replace("&amp;", "&")
    assert urlsplit(more).path == "/players"
    assert query_of_url(more) == {"country": "PL", "status": "active", "order": "desc", "cursor": "NEXT"}


def query_of_url(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_no_load_more_on_the_last_page(make_client):
    client = make_client({"/v1/players": page([PLAYER])})
    assert "load-more-row" not in client.get("/players").get_data(as_text=True)


def test_empty_list_says_so(make_client):
    client = make_client({"/v1/players": page([])})
    assert "No players match these filters." in client.get("/players").get_data(as_text=True)


def test_empty_later_page_does_not_say_no_players(make_client):
    # a "load more" that comes back empty: rows already above it, so no empty message
    client = make_client({"/v1/players": page([])})
    html = client.get("/players?cursor=abc", headers=HTMX).get_data(as_text=True)
    assert "No players" not in html


def test_bad_cursor_from_the_api_is_a_400(make_client):
    client = make_client({"/v1/players": (400, {"detail": "Invalid cursor."})})
    assert client.get("/players?cursor=garbage").status_code == 400


# ------------------------------------------------------------------ go to player

@pytest.mark.parametrize("typed", ["5", " 5 ", "#5", "005"])
def test_go_redirects_to_the_player(make_client, typed):
    response = make_client().get("/players/go", query_string={"id": typed})
    assert response.status_code == 302
    assert response.headers["Location"] == "/players/5"


@pytest.mark.parametrize("typed", ["", "abc", "0", "-3", "5.5"])
def test_go_rejects_what_is_not_an_id(make_client, typed):
    response = make_client().get("/players/go", query_string={"id": typed})
    assert response.status_code == 400
    assert "positive whole number" in response.get_data(as_text=True)


# ------------------------------------------------------------------ the player page

def test_player_page_shows_profile_balance_and_first_tab(make_client):
    client = make_client(player_api(transactions=page([TRANSACTION])))
    response = client.get("/players/5")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Player #5" in html
    assert "1,234,567.10 PLN" in html                  # balance, grouped
    assert "2,000,000.00" in html                      # deposited
    assert 'id="tabs"' in html
    assert "250.00 PLN" in html and "4242" in html     # the transactions tab
    (call,) = calls_to(client, "/v1/players/5/transactions")
    assert query_of(call) == {"limit": "25", "order": "desc"}


def test_active_tab_is_highlighted_by_the_server(make_client):
    client = make_client(player_api(bets=page([BET])))
    html = client.get("/players/5?tab=bets").get_data(as_text=True)
    active = re.findall(r'<a href="(/players/5\?tab=\w+)"[^>]*class="active"', html)
    assert active == ["/players/5?tab=bets"]
    assert "#900" in html and "43.00 PLN" in html


def test_htmx_tab_switch_gets_the_tab_only(make_client):
    client = make_client(player_api(sessions=page([SESSION])))
    html = client.get("/players/5?tab=sessions", headers=HTMX).get_data(as_text=True)
    assert "<html" not in html and "Player #5" not in html
    assert 'class="tabs' in html and "<table" in html
    # the profile and balance are not fetched again for a tab switch
    assert not calls_to(client, "/v1/players/5")
    assert not calls_to(client, "/v1/players/5/balance")


def test_htmx_load_more_on_a_tab_gets_rows_only(make_client):
    client = make_client(player_api(bets=page([BET], next_cursor="B2")))
    html = client.get("/players/5?tab=bets&cursor=B1", headers=HTMX).get_data(as_text=True)
    assert "<table" not in html and 'class="tabs' not in html
    assert html.lstrip().startswith("<tr>")
    assert 'hx-get="/players/5?tab=bets&amp;cursor=B2"' in html
    (call,) = calls_to(client, "/v1/players/5/bets")
    assert query_of(call) == {"limit": "25", "order": "desc", "cursor": "B1"}


def test_back_button_restore_gets_the_full_page(make_client):
    client = make_client(player_api())
    headers = {**HTMX, "HX-History-Restore-Request": "true"}
    html = client.get("/players/5?tab=linked", headers=headers).get_data(as_text=True)
    assert "<html" in html and "Player #5" in html


def test_responses_vary_on_hx_request(make_client):
    client = make_client({"/v1/players": page([])})
    assert "HX-Request" in client.get("/players").headers["Vary"]


def test_linked_tab_lists_oldest_first_and_links_players(make_client):
    client = make_client(player_api(linked=page([LINKED])))
    html = client.get("/players/5?tab=linked").get_data(as_text=True)
    assert 'href="/players/77"' in html
    assert query_of(calls_to(client, "/v1/players/5/linked")[0])["order"] == "asc"


def test_sessions_escape_the_user_agent_and_shorten_the_device(make_client):
    client = make_client(player_api(sessions=page([SESSION])))
    html = client.get("/players/5?tab=sessions").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert 'title="5e6d9db3-2217-4f70-b646-9a1f5f7402f2">5e6d9db3…' in html


@pytest.mark.parametrize("tab,empty", [
    ("transactions", "No deposits or withdrawals."),
    ("bets", "No bets."),
    ("sessions", "No logins."),
    ("linked", "No other player shares"),
])
def test_empty_tabs_say_so(make_client, tab, empty):
    client = make_client(player_api())
    assert empty in client.get(f"/players/5?tab={tab}").get_data(as_text=True)


def test_unknown_tab_is_a_404(make_client):
    client = make_client(player_api())
    assert client.get("/players/5?tab=secrets").status_code == 404
    assert not client.transport.seen[1:], "no API call for a tab that does not exist"


def test_unknown_player_is_a_404(make_client):
    client = make_client({"/v1/players/404404": (404, {"detail": "Player 404404 does not exist."})})
    response = client.get("/players/404404")
    assert response.status_code == 404


def test_player_pages_need_a_login(make_client):
    client = make_client(player_api(), logged_in=False)
    assert client.get("/players/5").status_code == 302
    assert client.get("/players").status_code == 302


def test_players_is_in_the_nav_and_active_on_player_pages(make_client):
    client = make_client(player_api())
    html = client.get("/players/5").get_data(as_text=True)
    assert 'href="/players" class="active"' in html


# ------------------------------------------------------------------ formatting

@pytest.mark.parametrize("amount,currency,shown", [
    ("0.00", "EUR", "0.00 EUR"),
    ("999.99", "EUR", "999.99 EUR"),
    ("1000.00", "EUR", "1,000.00 EUR"),
    ("-1234567.10", "PLN", "-1,234,567.10 PLN"),
    ("12.50", "", "12.50"),
    (None, "EUR", "-"),
])
def test_money(amount, currency, shown):
    assert money(amount, currency) == shown


def test_when():
    assert when("2026-08-18T19:42:07Z") == "2026-08-18 19:42 UTC"
    assert when("2026-08-18T21:42:07+02:00") == "2026-08-18 19:42 UTC"   # converted, not relabelled
    assert when(None) == "-"
