"""Panel tests. The API is replaced by httpx.MockTransport - no API, no database.

A test describes the API it wants as a dict:

    {"/ready": 200, "/v1/players": (401, {"detail": "..."})}

and gets a Flask test client whose every API call is answered from that dict. A
value can also be an exception (httpx.ConnectError, ...) to simulate an outage.
"""

import httpx
import pytest

from app import create_app

API_KEY = "super-secret-panel-key"     # long and unusual, so a leak is easy to search for


def fake_api(routes: dict):
    """An httpx transport answering from `routes`. Records every request it gets."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = routes.get(request.url.path, 404)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer if isinstance(answer, tuple) else (answer, {})
        if status >= 400:
            body = {"type": "about:blank", "title": "Error", "status": status, **body}
            return httpx.Response(status, json=body, headers={"content-type": "application/problem+json"})
        return httpx.Response(status, json=body)

    transport = httpx.MockTransport(handler)
    transport.seen = seen
    return transport


@pytest.fixture
def make_client():
    """make_client(routes) -> a Flask test client talking to a fake API."""
    def build(routes: dict | None = None):
        transport = fake_api(routes or {})
        app = create_app(
            {"api_url": "http://api.test", "api_key": API_KEY, "secret_key": "test"},
            transport=transport,
        )
        app.testing = True
        client = app.test_client()
        client.transport = transport
        client.flask_app = app
        return client
    return build


HEALTHY_API = {"/ready": (200, {"status": "ready"}), "/v1/players": (200, {"items": [], "next_cursor": None})}
