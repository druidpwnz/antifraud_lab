"""Logging in and out, and what a logged-out visitor can reach."""

import logging
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner
from dotenv import dotenv_values
from werkzeug.security import check_password_hash, generate_password_hash

from app.auth import hash_password, parse_users, safe_next
from tests.conftest import HEALTHY_API, TEST_PASSWORD, TEST_USER, csrf_token_from, login

# ---------------------------------------------------- logged out: what you can reach

def test_every_page_needs_a_login(make_client):
    client = make_client(HEALTHY_API, logged_in=False)

    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login?next=/"


def test_the_login_page_and_static_files_are_open(make_client):
    client = make_client(logged_in=False)

    assert client.get("/login").status_code == 200
    assert client.get("/static/vendor/beercss/beer.min.css").status_code == 200   # the login page needs it


def test_an_expired_session_during_htmx_navigates_the_whole_window(make_client):
    # A normal redirect would make htmx swap the login page INTO the status card.
    response = make_client(HEALTHY_API, logged_in=False).get("/status", headers={"HX-Request": "true"})

    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/login?next=/status"
    assert response.get_data() == b""


def test_a_logged_out_page_shows_no_navigation(make_client):
    html = make_client(logged_in=False).get("/login").get_data(as_text=True)

    assert 'class="left max l"' not in html
    assert "logout" not in html


# ------------------------------------------------------------------ logging in

def test_a_right_password_logs_in_and_goes_where_you_were_going(make_client):
    client = make_client(HEALTHY_API, logged_in=False)

    response = login(client, next_url="/status")

    assert response.status_code == 302
    assert response.headers["Location"] == "/status"
    assert client.get("/").status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(make_client):
    client = make_client(logged_in=False)

    wrong_password = login(client, password="nope").get_data(as_text=True)
    unknown_user = login(client, username="nobody").get_data(as_text=True)

    assert "Wrong username or password." in wrong_password
    assert "Wrong username or password." in unknown_user
    assert client.get("/").status_code == 302          # still not logged in


def test_a_failed_login_is_logged(make_client, caplog):
    with caplog.at_level(logging.WARNING):
        login(make_client(logged_in=False), password="nope")

    assert "failed login" in caplog.text


def test_login_without_a_csrf_token_is_refused(make_client):
    client = make_client(logged_in=False)

    response = client.post("/login", data={"username": TEST_USER, "password": TEST_PASSWORD})

    assert response.status_code == 400
    assert client.get("/").status_code == 302


def test_no_users_configured_means_nobody_gets_in(make_client, caplog):
    with caplog.at_level(logging.WARNING):
        client = make_client(logged_in=False, users="")

    assert "nobody can log in" in caplog.text
    assert "Wrong username or password." in login(client).get_data(as_text=True)


@pytest.mark.parametrize("target, goes_to", [
    ("/status", "/status"),
    ("/players?page=2", "/players?page=2"),
    ("https://evil.example/phish", "/"),       # an open redirect, the classic login-page bug
    ("//evil.example/phish", "/"),             # a protocol-relative URL is another site too
    ("javascript:alert(1)", "/"),
    ("", "/"),
    (None, "/"),
])
def test_next_only_goes_to_this_site(make_client, target, goes_to):
    with make_client(logged_in=False).flask_app.test_request_context():
        assert safe_next(target) == goes_to


def test_the_session_cookie_is_locked_down(make_client):
    client = make_client(logged_in=False)
    response = login(client)

    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


# ------------------------------------------------------------------ logging out

def test_logout_is_post_only(make_client):
    client = make_client(HEALTHY_API)

    assert client.get("/logout").status_code == 405
    assert client.get("/").status_code == 200          # still logged in


def test_logout_needs_the_csrf_token(make_client):
    client = make_client(HEALTHY_API)

    assert client.post("/logout").status_code == 400   # another site's form could do exactly this
    assert client.get("/").status_code == 200


def test_logout_logs_out(make_client):
    client = make_client(HEALTHY_API)
    token = csrf_token_from(client.get("/").get_data(as_text=True))

    response = client.post("/logout", data={"csrf_token": token})

    assert response.headers["Location"] == "/login"
    assert client.get("/").status_code == 302


def test_a_user_removed_from_admin_users_is_logged_out(make_client):
    client = make_client(HEALTHY_API)
    client.flask_app.extensions["users"].clear()      # as if ADMIN_USERS changed and the panel restarted

    assert client.get("/").status_code == 302


# ------------------------------------------------------------- ADMIN_USERS

def test_parse_users_splits_on_the_first_colon_only():
    password_hash = generate_password_hash("x")          # "scrypt:32768:8:1$...$..." - colons of its own

    assert parse_users(f"igor:{password_hash}, anna:{password_hash}") == {
        "igor": password_hash, "anna": password_hash,
    }
    assert parse_users("") == {}


def test_parse_users_rejects_a_malformed_entry():
    with pytest.raises(ValueError):
        parse_users("igor")


def test_a_real_hash_survives_a_trip_through_a_dotenv_file():
    # Hashes contain '$', and python-dotenv expands ${...} - even inside single quotes,
    # it turns out. A real hash is safe only because Werkzeug salts are letters and
    # digits, so '${' cannot occur. This checks that stays true.
    line = f"igor:{generate_password_hash('x')}"
    with tempfile.TemporaryDirectory() as d:
        env = Path(d) / ".env"
        env.write_text(f"ADMIN_USERS={line}\n")
        assert dotenv_values(env)["ADMIN_USERS"] == line


def test_hash_password_prints_a_ready_entry():
    result = CliRunner().invoke(hash_password, ["igor"], input="s3cret\ns3cret\n")

    name, _, password_hash = result.output.strip().splitlines()[-1].partition(":")
    assert name == "igor"
    assert check_password_hash(password_hash, "s3cret")


def test_hash_password_refuses_a_username_that_would_break_the_format():
    assert CliRunner().invoke(hash_password, ["a:b"], input="x\nx\n").exit_code != 0
