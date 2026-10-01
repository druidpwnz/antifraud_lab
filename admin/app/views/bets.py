"""Bets: every player's bets, newest first, and one bet in full.

    /bets                    the list; filters status, min_stake, order
    /bets?cursor=...         (htmx) the next page of rows, for "load more"
    /bets/go?id=900          the "Bet ID" box: redirects to /bets/900
    /bets/900                one bet: its legs, their matches, the settlement

Same shape as players.py: one URL, a full page normally, the rows alone for htmx.
"""

import re
from datetime import datetime
from decimal import Decimal

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for

from app.htmx import is_htmx

bp = Blueprint("bets", __name__, url_prefix="/bets")

PAGE_SIZE = 25
STATUSES = ["open", "won", "lost", "void", "cashed_out"]
ORDERS = {"desc": "Newest first", "asc": "Oldest first"}
# 500, 12.5, 12.50 - not -1, 1e3 or 1.234
AMOUNT = re.compile(r"[0-9]+(\.[0-9]{1,2})?")


def api():
    return current_app.extensions["api"]


@bp.get("")
def index():
    filters = {
        "status": request.args.get("status", ""),
        "min_stake": request.args.get("min_stake", "").strip(),
        "order": request.args.get("order", "desc"),
    }
    if filters["order"] not in ORDERS:
        filters["order"] = "desc"
    if filters["min_stake"] and not is_amount(filters["min_stake"]):
        abort(400, "Minimum stake is an amount, like 500 or 12.50.")
    cursor = request.args.get("cursor") or None

    page = api().get("/v1/bets", limit=PAGE_SIZE, cursor=cursor, **filters)
    context = {
        "bets": page["items"],
        "cursor": cursor,
        "more_url": url_for("bets.index", cursor=page["next_cursor"], **filters)
                    if page["next_cursor"] else None,
        "filters": filters,
        "statuses": STATUSES,
        "orders": ORDERS,
    }
    if is_htmx():
        return render_template("bets/_rows.html", **context)
    return render_template("bets/index.html", **context)


def is_amount(text: str) -> bool:
    """What the API accepts as min_stake: a plain amount, at most two decimals. Checked
    here too, so a typo gets a sentence in plain words instead of the API's 422."""
    return AMOUNT.fullmatch(text) is not None


@bp.get("/go")
def go():
    bet_id = request.args.get("id", "").strip().lstrip("#")
    if not bet_id.isdigit() or int(bet_id) == 0:
        abort(400, "A bet ID is a positive whole number.")
    return redirect(url_for("bets.show", bet_id=int(bet_id)))


@bp.get("/<int:bet_id>")
def show(bet_id: int):
    bet = api().get(f"/v1/bets/{bet_id}")
    return render_template("bets/show.html", bet=bet, warnings=warnings_for(bet))


def warnings_for(bet: dict) -> list[str]:
    """Things a reviewer should look at, read straight off the bet.

    Not fraud detection - that is Phase 9's job, in Prometheus. These are facts
    anyone can check in the data on this page, said out loud so they are not missed:
    a leg placed after its match kicked off, and a payout that does not fit the
    result. Nothing here reads fraud_labels; the panel cannot even reach it.
    """
    found = []
    placed_at = datetime.fromisoformat(bet["placed_at"])
    for leg in bet["legs"]:
        # parsed, not compared as strings: "12:00:00.5Z" sorts before "12:00:00Z"
        if placed_at > datetime.fromisoformat(leg["event"]["start_time"]):
            found.append(f"Placed after kickoff of {leg['event']['home_team']} – "
                         f"{leg['event']['away_team']}.")
    settlement = bet["settlement"]
    if settlement and settlement["result"] == "lost" and Decimal(settlement["payout"]) > 0:
        found.append("Settled as lost, but paid out.")
    if settlement and settlement["result"] == "won":
        expected = (Decimal(bet["stake"]) * Decimal(bet["total_odds"])).quantize(Decimal("0.01"))
        if abs(Decimal(settlement["payout"]) - expected) > Decimal("0.01"):
            found.append(f"Won, but paid {settlement['payout']} - stake × odds is {expected}.")
    return found
