"""The home page, and the API status card it polls."""

from flask import Blueprint, current_app, render_template

from app.api_client import ApiError, ApiUnavailable

bp = Blueprint("home", __name__)


@bp.get("/")
def index():
    return render_template("home.html")


@bp.get("/status")
def status():
    """Is the API up, and does it accept the panel's key?

    Two separate questions, two calls. /ready needs no key, so it answers the first
    alone; a /v1 call answers the second. A panel with a wrong key looks fine on
    /ready and fails on every real page - this card says which it is.

    Never raises: the card must render even when everything is broken.
    """
    api = current_app.extensions["api"]
    state = {"reachable": False, "key_ok": False, "message": None}
    try:
        api.get("/ready")
        state["reachable"] = True
        api.get("/v1/players", limit=1)
        state["key_ok"] = True
    except ApiUnavailable as exc:
        state["message"] = str(exc)
    except ApiError as exc:
        if exc.status in (401, 403):
            state["message"] = "the API does not accept the panel's key"
        elif exc.status == 503:
            state["reachable"] = True   # the API is up; its database is not
            state["message"] = "the API cannot reach its database"
        else:
            state["message"] = f"the API answered {exc.status}"
    return render_template("_api_status.html", **state)
