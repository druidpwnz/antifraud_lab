"""The admin panel: a Flask app that shows what the API knows.

    browser --HTML--> this panel --HTTP + X-API-Key--> the API --> Postgres

The browser never talks to the API. htmx asks the panel, and the panel calls the API
server-side, so the API key exists only in the panel's environment.

Run from the admin/ directory:
    flask --app app run --port 5000 --debug
"""

import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

from app import config as config_module
from app.api_client import ApiClient, ApiError, ApiUnavailable
from app.htmx import render
from app.auth import init_auth
from app.views import home

log = logging.getLogger(__name__)

# Locked down on purpose. Everything is served from this origin - the libraries are
# vendored - so nothing else is allowed: no CDN, no inline scripts, no inline styles,
# no eval. If a template ever needs an exception, it shows up here, in review.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",       # Beer CSS draws a couple of tiny patterns as data: images
    "font-src 'self'",            # blocks the CDN fallback in beer.min.css's @font-face
    "connect-src 'self'",         # htmx may only call this panel, never the API directly
    "frame-ancestors 'none'",     # nobody may put the panel in an iframe
    "base-uri 'self'",
    "form-action 'self'",
])


def create_app(overrides: dict | None = None, transport=None) -> Flask:
    """Build the app. Tests pass `overrides` for the config and an httpx MockTransport
    as `transport`, so they need neither a real API nor environment variables."""
    app = Flask(__name__)
    cfg = config_module.load(overrides)
    app.config["PANEL"] = cfg
    app.secret_key = cfg.secret_key

    app.extensions["api"] = ApiClient(cfg.api_url, cfg.api_key, cfg.api_timeout, transport)

    init_auth(app)                  # every page needs a login from here on
    app.register_blueprint(home.bp)
    register_error_pages(app)

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    return app


def register_error_pages(app: Flask) -> None:
    """What the panel shows when something fails. Decided here, once, for every view."""

    def page(status: int, title: str, message: str, retry: bool = False):
        # An htmx request gets only the error card, swapped in where the content would
        # have gone; a normal request gets a whole page around it.
        return render("errors/error.html", "errors/_error.html", status=status, title=title,
                      message=message, retry=retry), status

    @app.errorhandler(ApiUnavailable)
    def api_unavailable(exc):
        return page(503, "API unavailable", f"The panel could not get data: {exc}.", retry=True)

    @app.errorhandler(ApiError)
    def api_error(exc: ApiError):
        if exc.status == 404:
            return page(404, "Not found", exc.detail or "That does not exist.")
        if exc.status in (400, 422):
            return page(400, "Bad request", exc.detail or "The API did not accept that request.")
        if exc.status in (401, 403):
            # Not the user's fault, and nothing they can fix: the panel's own key is
            # wrong. Log it for whoever runs the panel; show a plain 500, and never the key.
            log.error("the API rejected the panel's API key (%s) - check API_KEY", exc.status)
            return page(500, "Panel misconfigured",
                        "The panel is not allowed to read from the API. Whoever runs it needs to check its API key.")
        log.error("the API failed: %s", exc)
        return page(502, "The API failed", "The API answered with an error. Try again in a moment.", retry=True)

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        return page(exc.code or 500, exc.name, exc.description or "")

    @app.errorhandler(Exception)
    def unexpected(exc):
        log.exception("unhandled error")
        return page(500, "Something went wrong", "Something went wrong in the panel.")
