"""The panel's skeleton: layout, the API status card, error pages, security headers."""

import logging
import re
from pathlib import Path

import httpx
import pytest
from flask import Blueprint, current_app

from app.api_client import ApiClient, ApiError
from tests.conftest import API_KEY, HEALTHY_API, fake_api

TEMPLATES = Path(__file__).parent.parent / "app" / "templates"


# ---------------------------------------------------------------- the layout

def test_home_is_a_full_page_with_the_layout(make_client):
    html = make_client(HEALTHY_API).get("/").get_data(as_text=True)

    assert "<html" in html
    assert "vendor/beercss/beer.min.css" in html
    assert "vendor/htmx/htmx.min.js" in html
    assert 'hx-get="/status"' in html            # the status card loads itself


def test_vendored_assets_are_served(make_client):
    client = make_client()
    for path in ("vendor/beercss/beer.min.css", "vendor/htmx/htmx.min.js", "app.css",
                 "vendor/beercss/material-symbols-outlined.woff2",
                 "vendor/roboto/roboto-latin-wght-normal.woff2"):
        assert client.get(f"/static/{path}").status_code == 200, path


# ------------------------------------------------------------ the status card

@pytest.mark.parametrize("routes, expected", [
    (HEALTHY_API, "Online"),
    ({"/ready": 200, "/v1/players": (401, {"detail": "no"})}, "does not accept the panel&#39;s key"),
    ({"/ready": 200, "/v1/players": (403, {"detail": "no"})}, "does not accept the panel&#39;s key"),
    ({"/ready": (503, {"detail": "database unavailable"})}, "cannot reach its database"),
    ({"/ready": httpx.ConnectError("refused")}, "could not be reached"),
    ({"/ready": httpx.ReadTimeout("slow")}, "did not answer in time"),
])
def test_status_card_says_what_is_wrong(make_client, routes, expected):
    response = make_client(routes).get("/status", headers={"HX-Request": "true"})

    assert response.status_code == 200          # the card always renders
    assert expected in response.get_data(as_text=True)


def test_status_card_is_a_fragment_not_a_page(make_client):
    html = make_client(HEALTHY_API).get("/status", headers={"HX-Request": "true"}).get_data(as_text=True)

    assert "<html" not in html


# --------------------------------------------- what an API failure turns into

@pytest.fixture
def probe(make_client):
    """A panel with one extra route that just asks the API for /probe."""
    def build(answer):
        bp = Blueprint("probe", __name__)

        @bp.get("/probe")
        def probe_view():
            current_app.extensions["api"].get("/probe")
            return "fine"

        return make_client({"/probe": answer}, blueprints=(bp,))
    return build


@pytest.mark.parametrize("answer, status, says", [
    ((404, {"detail": "Player 9 does not exist."}), 404, "Player 9 does not exist."),
    ((422, {"detail": "limit too big"}), 400, "limit too big"),
    ((401, {"detail": "Missing or invalid API key."}), 500, "Panel misconfigured"),
    ((403, {"detail": "not allowed"}), 500, "Panel misconfigured"),
    ((500, {"detail": "boom"}), 502, "The API failed"),
    (httpx.ConnectError("refused"), 503, "API unavailable"),
])
def test_api_failures_become_panel_pages(probe, answer, status, says):
    response = probe(answer).get("/probe")

    assert response.status_code == status
    assert says in response.get_data(as_text=True)


def test_an_outage_offers_a_retry(probe):
    html = probe(httpx.ConnectError("refused")).get("/probe").get_data(as_text=True)

    assert "Try again" in html


def test_a_wrong_panel_key_is_logged_for_whoever_runs_it(probe, caplog):
    with caplog.at_level(logging.ERROR):
        probe((401, {"detail": "Missing or invalid API key."})).get("/probe")

    assert "API_KEY" in caplog.text


def test_an_htmx_request_that_fails_gets_only_the_error_card(probe):
    response = probe((404, {"detail": "gone"})).get("/probe", headers={"HX-Request": "true"})

    html = response.get_data(as_text=True)
    assert response.status_code == 404
    assert "gone" in html
    assert "<html" not in html        # swapped into the page, not a page inside the page


def test_unknown_panel_url_is_a_404_page(make_client):
    response = make_client().get("/no/such/page")

    assert response.status_code == 404
    assert "Not Found" in response.get_data(as_text=True)


# ------------------------------------------------------------------- security

def test_the_api_key_never_reaches_the_browser(make_client, probe):
    # The point of the panel calling the API server-side: the key stays on the server.
    pages = [
        make_client(HEALTHY_API).get("/"),
        make_client(HEALTHY_API).get("/status", headers={"HX-Request": "true"}),
        make_client({"/ready": 200, "/v1/players": (401, {})}).get("/status"),
        probe((401, {"detail": "Missing or invalid API key."})).get("/probe"),
        probe(httpx.ConnectError("refused")).get("/probe"),
        make_client().get("/missing"),
        make_client(logged_in=False).get("/login"),
    ]
    for response in pages:
        assert API_KEY not in response.get_data(as_text=True)
        assert API_KEY not in str(response.headers)


def test_the_panel_sends_its_key_to_the_api(make_client):
    client = make_client(HEALTHY_API)
    client.get("/status", headers={"HX-Request": "true"})

    assert all(r.headers["X-API-Key"] == API_KEY for r in client.transport.seen)


def test_security_headers_on_pages_errors_and_assets(make_client):
    client = make_client(HEALTHY_API)
    for url in ("/", "/missing", "/static/app.css"):
        headers = client.get(url).headers
        assert "default-src 'self'" in headers["Content-Security-Policy"], url
        assert "font-src 'self'" in headers["Content-Security-Policy"], url
        assert headers["X-Content-Type-Options"] == "nosniff", url


def test_no_template_has_inline_scripts_or_styles():
    # The CSP blocks both; this catches them in review instead of as a silently
    # broken page in the browser.
    for template in TEMPLATES.rglob("*.html"):
        # Jinja comments {# ... #} never reach the browser, and base.html has one that
        # mentions <style> while explaining why htmx's injected styles are switched off.
        source = re.sub(r"\{#.*?#\}", "", template.read_text(), flags=re.S)
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", source), f"inline <script> in {template.name}"
        assert not re.search(r"\sstyle=", source), f"style= attribute in {template.name}"
        assert "<style" not in source, f"<style> in {template.name}"


# ----------------------------------------------------------- the API client

def test_empty_filters_are_not_sent():
    transport = fake_api({"/v1/players": 200})
    ApiClient("http://api.test", "k", 1, transport).get("/v1/players", country="", status=None, limit=5)

    assert str(transport.seen[0].url) == "http://api.test/v1/players?limit=5"


def test_an_error_that_is_not_json_still_becomes_an_api_error():
    def handler(request):
        return httpx.Response(502, text="<html>bad gateway</html>")

    client = ApiClient("http://api.test", "k", 1, httpx.MockTransport(handler))
    with pytest.raises(ApiError) as caught:
        client.get("/anything")

    assert caught.value.status == 502
    assert caught.value.title == "Bad Gateway"
