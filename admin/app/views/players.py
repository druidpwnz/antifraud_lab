"""Players: the list, and one player with their money, bets, logins and links.

Both pages follow the panel's one rule for htmx: one URL, two answers.

  /players                       full page            first page of the list
  /players?country=UA  (htmx)    rows only            the filter changed
  /players?cursor=...  (htmx)    rows only            "load more"

  /players/5                     full page            header, balance, first tab
  /players/5?tab=bets  (htmx)    tab bar + table      a tab was clicked
  /players/5?tab=bets&cursor=... (htmx) rows only     "load more" inside a tab

Filters and tabs live in the URL, so a filtered list or a tab can be bookmarked and
shared, the back button works, and every page still works with JavaScript off.
"""

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for

from app.htmx import is_htmx

bp = Blueprint("players", __name__, url_prefix="/players")

PAGE_SIZE = 25

# What the filter drop-downs offer. Countries are the generator's: the API has no
# "list countries" endpoint, and a free text box would let a typo become a 400.
COUNTRIES = ["DE", "ES", "GB", "PL", "UA"]
STATUSES = ["active", "suspended", "closed", "self_excluded"]
ORDERS = {"desc": "Newest first", "asc": "Oldest first"}

# The player page's tabs: which API list each shows, and how.
TABS = {
    "transactions": {
        "label": "Transactions", "icon": "payments", "path": "transactions", "order": "desc",
        "columns": ["", "Amount", "Status", "Method", "Created", "Processed"],
        "empty": "No deposits or withdrawals.",
    },
    "bets": {
        "label": "Bets", "icon": "sports_soccer", "path": "bets", "order": "desc",
        "columns": ["Bet", "Placed", "Stake", "Odds", "Status", "Payout"],
        "empty": "No bets.",
    },
    "sessions": {
        "label": "Sessions", "icon": "devices", "path": "sessions", "order": "desc",
        "columns": ["Started", "Ended", "IP", "Device", "User agent"],
        "empty": "No logins.",
    },
    "linked": {
        "label": "Linked", "icon": "hub", "path": "linked", "order": "asc",
        "columns": ["Player", "Country", "Status", "Shared devices", "Shared payment methods", "Registered"],
        "empty": "No other player shares a device or a payment method with this one.",
    },
}


def api():
    return current_app.extensions["api"]


@bp.get("")
def index():
    filters = {
        "country": request.args.get("country", ""),
        "status": request.args.get("status", ""),
        "order": request.args.get("order", "desc"),
    }
    if filters["order"] not in ORDERS:
        filters["order"] = "desc"
    cursor = request.args.get("cursor") or None

    page = api().get("/v1/players", limit=PAGE_SIZE, cursor=cursor, **filters)
    context = {
        "players": page["items"],
        "cursor": cursor,
        # the next page keeps the same filters - a cursor is only valid with them
        "more_url": url_for("players.index", cursor=page["next_cursor"], **filters)
                    if page["next_cursor"] else None,
        "filters": filters,
        "countries": COUNTRIES, "statuses": STATUSES, "orders": ORDERS,
    }
    if is_htmx():
        return render_template("players/_rows.html", **context)
    return render_template("players/index.html", **context)


@bp.get("/go")
def go():
    """The "go to player #..." box: a redirect to that player's page."""
    player_id = request.args.get("id", "").strip().lstrip("#")
    if not player_id.isdigit() or int(player_id) == 0:
        abort(400, "A player ID is a positive whole number.")
    return redirect(url_for("players.show", player_id=int(player_id)))


@bp.get("/<int:player_id>")
def show(player_id: int):
    tab = request.args.get("tab", "transactions")
    if tab not in TABS:
        abort(404, f"There is no '{tab}' tab.")
    cursor = request.args.get("cursor") or None

    # "load more" inside a tab: just the next rows
    if is_htmx() and cursor:
        return render_template("players/_tab_rows.html",
                               **tab_context(player_id, tab, cursor))

    # a tab was clicked: the tab bar and the new table, nothing above them
    if is_htmx():
        return render_template("players/_tabs.html", **tab_context(player_id, tab, None))

    # the whole page. The player first: an unknown id is a 404 before anything else.
    player = api().get(f"/v1/players/{player_id}")
    balance = api().get(f"/v1/players/{player_id}/balance")
    return render_template("players/show.html", player=player, balance=balance,
                           **tab_context(player_id, tab, None))


def tab_context(player_id: int, tab: str, cursor: str | None) -> dict:
    info = TABS[tab]
    page = api().get(f"/v1/players/{player_id}/{info['path']}",
                     limit=PAGE_SIZE, order=info["order"], cursor=cursor)
    return {
        "player_id": player_id,
        "tab": tab,
        "tab_info": info,
        "tabs": TABS,
        "rows": page["items"],
        "cursor": cursor,
        "more_url": url_for("players.show", player_id=player_id, tab=tab,
                            cursor=page["next_cursor"]) if page["next_cursor"] else None,
    }
