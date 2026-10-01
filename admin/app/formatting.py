"""How values from the API are shown. Registered as Jinja filters in create_app.

Money arrives as a string - "1234567.10" - and is formatted as a string. It is never
turned into a float on the way, for the same reason the API sends it as a string.
"""

from datetime import UTC, datetime

# Chip colours by status: a tone-<name> class in app.css. Anything unknown is plain.
STATUS_COLOURS = {
    "active": "green", "suspended": "amber", "closed": "grey", "self_excluded": "deep-orange",
    "approved": "green", "pending": "amber", "rejected": "red", "chargeback": "red",
    "won": "green", "lost": "red", "open": "blue", "void": "grey", "cashed_out": "teal",
    "scheduled": "blue", "live": "deep-orange", "finished": "grey", "cancelled": "grey",
    "postponed": "amber",
}


def money(amount: str | None, currency: str = "") -> str:
    """ "1234567.10", "PLN" -> "1,234,567.10 PLN". Digit grouping done on the string."""
    if amount is None:
        return "-"
    sign = "-" if amount.startswith("-") else ""
    whole, _, cents = amount.lstrip("-").partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    text = sign + ",".join(groups) + (f".{cents}" if cents else "")
    return f"{text} {currency}".strip()


def when(value: str | None) -> str:
    """ "2026-08-18T19:42:07Z" -> "2026-08-18 19:42 UTC". Always UTC, said out loud:
    the API's times are UTC, and showing them in whatever zone the browser is in would
    make two people looking at the same row see different times."""
    if not value:
        return "-"
    moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def status_colour(status: str) -> str:
    return STATUS_COLOURS.get(status, "")


def humanise(value: str) -> str:
    """ "self_excluded" -> "self excluded" """
    return value.replace("_", " ")
