"""One URL, two answers.

A normal request gets the full page. An htmx request - it sends `HX-Request: true` -
gets only the fragment it asked for, to swap into the page it already has. So every
page still works with JavaScript off, and htmx just makes it quicker.
"""

from flask import render_template, request


def is_htmx() -> bool:
    """True when htmx wants a fragment.

    One exception: going Back to a page htmx no longer has in its history cache. htmx
    then re-asks the URL with HX-History-Restore-Request and replaces the whole body
    with the answer, so that answer must be the full page.
    """
    return (request.headers.get("HX-Request") == "true"
            and request.headers.get("HX-History-Restore-Request") != "true")


def render(page: str, fragment: str, **context) -> str:
    """The fragment for htmx, the whole page otherwise. The page template includes
    the fragment, so both always show the same thing."""
    return render_template(fragment if is_htmx() else page, **context)
