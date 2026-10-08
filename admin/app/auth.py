"""Logging in to the panel.

The panel has no database, so its users live in the environment:

    ADMIN_USERS=igor:scrypt:32768:8:1$Fq3...$9b1...,anna:scrypt:...

A username, a colon, then a Werkzeug password hash (the hash has colons of its own,
so only the FIRST colon splits). Make a line with:

    flask --app app hash-password igor

Every page needs a logged-in user, except the login page and the static files. That
is enforced once, in require_login() before every request - the same idea as the
API's key check on the /v1 router: a new page is protected by default, and
forgetting a decorator cannot leave one open.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

import click
from flask import (Blueprint, Flask, current_app, redirect, render_template, request,
                   session, url_for)
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired

from app.htmx import is_htmx

log = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)
login_manager = LoginManager()
csrf = CSRFProtect()

# Pages anyone may open. Everything else needs a login.
PUBLIC_ENDPOINTS = {"auth.login", "static", "home.health"}

# Checked against when the username does not exist, so a wrong username takes as long
# as a wrong password. Otherwise the response time tells an attacker which usernames
# are real.
_DUMMY_HASH = generate_password_hash("not a real password")


@dataclass(frozen=True)
class User(UserMixin):
    id: str          # the username; Flask-Login keeps it in the session cookie


def parse_users(line: str) -> dict[str, str]:
    """ "igor:<hash>,anna:<hash>" -> {"igor": "<hash>", "anna": "<hash>"}"""
    users = {}
    for entry in filter(None, (e.strip() for e in line.split(","))):
        name, sep, password_hash = entry.partition(":")
        if not sep or not name or not password_hash:
            raise ValueError(f"ADMIN_USERS entry is not 'name:hash': {name!r}")
        users[name] = password_hash
    return users


class LoginForm(FlaskForm):
    # FlaskForm adds a hidden csrf_token field and refuses a POST without it
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])


def init_auth(app: Flask) -> None:
    cfg = app.config["PANEL"]
    app.extensions["users"] = parse_users(cfg.admin_users)
    if not app.extensions["users"]:
        log.warning("ADMIN_USERS is empty - nobody can log in")

    # The session is a signed cookie. HttpOnly: page scripts cannot read it.
    # SameSite=Lax: other sites cannot send it along with a form they submit to us.
    # Secure: only over HTTPS - off by default because the panel runs on plain http
    # locally; switch it on (SECURE_COOKIES=1) behind HTTPS.
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cfg.secure_cookies,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=cfg.session_hours),
    )

    login_manager.init_app(app)
    login_manager.session_protection = "strong"
    csrf.init_app(app)
    app.register_blueprint(bp)
    app.before_request(require_login)
    app.cli.add_command(hash_password)


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    # A user removed from ADMIN_USERS is logged out on their next request.
    return User(user_id) if user_id in current_app.extensions["users"] else None


def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS or current_user.is_authenticated:
        return None
    login_url = url_for("auth.login", next=request.full_path.rstrip("?"))
    if is_htmx():
        # An htmx request is fetching a fragment for a page already on screen. A
        # normal redirect would make htmx swap the LOGIN PAGE into that fragment's
        # place. HX-Redirect tells htmx to navigate the whole window instead.
        return "", 401, {"HX-Redirect": login_url}
    return redirect(login_url)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home.index"))
    form = LoginForm()
    error = None
    if form.validate_on_submit():
        users = current_app.extensions["users"]
        password_hash = users.get(form.username.data)
        # Always run one hash check, real or dummy, so both kinds of mistake take the
        # same time; and give one message for both, so neither reveals the other.
        ok = check_password_hash(password_hash or _DUMMY_HASH, form.password.data)
        if password_hash and ok:
            session.clear()                 # a fresh session: nothing carried over from before login
            session.permanent = True        # expire after SESSION_HOURS, not when the browser closes
            login_user(User(form.username.data))
            log.info("login: %s", form.username.data)
            return redirect(safe_next(request.args.get("next")))
        log.warning("failed login for %r", form.username.data)
        error = "Wrong username or password."
    # 200 even when it failed: 401 is for HTTP authentication and must name a scheme in
    # WWW-Authenticate, which a login form does not have. The failure is in the log.
    return render_template("login.html", form=form, error=error)


@bp.post("/logout")
def logout():
    # POST, not GET, and behind the CSRF check: a logout link would let any page you
    # visit log you out with an <img src="/logout">.
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))


def safe_next(target: str | None) -> str:
    """Where to go after login: a path on THIS site, or home.

    `next` comes from the URL, so anyone can write a link to
    /login?next=https://evil.example - and send our users there right after they type
    their password. Only a plain local path is followed.
    """
    if target:
        parts = urlsplit(target)
        if not parts.scheme and not parts.netloc and target.startswith("/") and not target.startswith("//"):
            return target
    return url_for("home.index")


@click.command("hash-password")
@click.argument("username")
def hash_password(username: str) -> None:
    """Print an ADMIN_USERS entry for USERNAME. Asks for the password twice."""
    if ":" in username or "," in username:
        raise click.BadParameter("a username cannot contain ':' or ','")
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    click.echo(f"{username}:{generate_password_hash(password)}")
