"""Events: matches in kickoff order, and one match with its markets and prices.

    /events                  upcoming matches, soonest first; filters status, league
    /events?cursor=...       (htmx) the next page of rows, for "load more"
    /events/482              one match: every market, every selection, current odds

The list always asks the API for sort=start_time. Kickoff times repeat - five a day -
which is why the API's cursor carries (start_time, id): load more never skips a
match that shares a kickoff with the last row of the page before.
"""

from flask import Blueprint, current_app, render_template, request, url_for

from app.htmx import is_htmx

bp = Blueprint("events", __name__, url_prefix="/events")

PAGE_SIZE = 25
# "" is every status. Upcoming is the default: it is what a back office looks at.
STATUSES = {"scheduled": "Upcoming", "live": "Live", "finished": "Finished",
            "postponed": "Postponed", "cancelled": "Cancelled", "": "Any"}
# The generator's leagues (generator/config.py). The API has no "list leagues"
# endpoint, and five fixed names do not justify one.
LEAGUES = ["Premier League", "La Liga", "Bundesliga", "Ekstraklasa", "Premier Liha"]
ORDERS = {"asc": "Soonest first", "desc": "Latest first"}


def api():
    return current_app.extensions["api"]


@bp.get("")
def index():
    filters = {
        "status": request.args.get("status", "scheduled"),
        "league": request.args.get("league", ""),
        "order": request.args.get("order", "asc"),
    }
    if filters["status"] not in STATUSES:
        filters["status"] = "scheduled"
    if filters["order"] not in ORDERS:
        filters["order"] = "asc"
    cursor = request.args.get("cursor") or None

    page = api().get("/v1/events", sort="start_time", limit=PAGE_SIZE, cursor=cursor, **filters)
    context = {
        "events": page["items"],
        "cursor": cursor,
        "more_url": url_for("events.index", cursor=page["next_cursor"], **filters)
                    if page["next_cursor"] else None,
        "filters": filters,
        "statuses": STATUSES,
        "leagues": LEAGUES,
        "orders": ORDERS,
    }
    if is_htmx():
        return render_template("events/_rows.html", **context)
    return render_template("events/index.html", **context)


@bp.get("/<int:event_id>")
def show(event_id: int):
    return render_template("events/show.html", event=api().get(f"/v1/events/{event_id}"))
