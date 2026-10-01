"""Panel tests. The API is replaced by httpx.MockTransport - no API, no database.

A test describes the API it wants as a dict:

    {"/ready": 200, "/v1/players": (401, {"detail": "..."})}

and gets a Flask test client whose every API call is answered from that dict. A
value can also be an exception (httpx.ConnectError, ...) to simulate an outage.
"""

import re

import httpx
import pytest
from werkzeug.security import generate_password_hash

from app import create_app

API_KEY = "super-secret-panel-key"     # long and unusual, so a leak is easy to search for

TEST_USER = "tester"
TEST_PASSWORD = "correct horse battery staple"
# A deliberately cheap hash so the suite stays fast. Real hashes from `flask
# hash-password` use Werkzeug's default, scrypt, which is slow on purpose.
TEST_HASH = generate_password_hash(TEST_PASSWORD, method="pbkdf2:sha256:1000")


def csrf_token_from(html: str) -> str:
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)


def login(client, username=TEST_USER, password=TEST_PASSWORD, next_url=None):
    """Log in through the real form: GET it for a CSRF token, then POST it."""
    token = csrf_token_from(client.get("/login").get_data(as_text=True))
    url = "/login" + (f"?next={next_url}" if next_url else "")
    return client.post(url, data={"username": username, "password": password, "csrf_token": token})


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
    """make_client(routes) -> a logged-in Flask test client talking to a fake API.
    make_client(routes, logged_in=False) for one that has not logged in."""
    def build(routes: dict | None = None, logged_in: bool = True, users: str | None = None,
              blueprints: tuple = ()):
        transport = fake_api(routes or {})
        app = create_app(
            {"api_url": "http://api.test", "api_key": API_KEY, "secret_key": "test",
             "admin_users": f"{TEST_USER}:{TEST_HASH}" if users is None else users},
            transport=transport,
        )
        # extra test-only routes go in now: Flask refuses new routes once the app has
        # handled a request, and logging in below is a request
        for bp in blueprints:
            app.register_blueprint(bp)
        app.testing = True
        client = app.test_client()
        client.transport = transport
        client.flask_app = app
        if logged_in:
            assert login(client).status_code == 302, "test login failed"
        return client
    return build


HEALTHY_API = {"/ready": (200, {"status": "ready"}), "/v1/players": (200, {"items": [], "next_cursor": None})}
