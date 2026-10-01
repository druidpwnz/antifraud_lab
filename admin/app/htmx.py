"""One URL, two answers.

A normal request gets the full page. An htmx request - it sends `HX-Request: true` -
gets only the fragment it asked for, to swap into the page it already has. So every
page still works with JavaScript off, and htmx just makes it quicker.
"""

from flask import render_template, request


def is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


def render(page: str, fragment: str, **context) -> str:
    """The fragment for htmx, the whole page otherwise. The page template includes
    the fragment, so both always show the same thing."""
    return render_template(fragment if is_htmx() else page, **context)
