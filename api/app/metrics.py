"""Prometheus metrics: requests, latency, risk decisions.

Served on their own port (METRICS_PORT, 9100 in compose, never published), not on
/metrics next to the API: the API's port is on the LAN, its metrics are for
Prometheus only. Off when METRICS_PORT is unset - locally, and in the tests.

Labels are small fixed sets, never ids. A series is one combination of label
values, so a label taken from the raw URL - /v1/players/532 - would make a series
per player and take Prometheus down. Requests are labelled by the ROUTE TEMPLATE,
/v1/players/{player_id}, looked up in the API's own OpenAPI document.

Not from the matched route alone: FastAPI 0.141 nests included routers, so the
route in the request scope knows only its own part, /players/{player_id}, and not
the /v1 of the router around it. The OpenAPI document has the full templates, and
it is public API - unlike the internals that hold the prefix.

The metrics server runs in a thread of this process, which is right for the one
uvicorn worker that runs today. Several workers would each have their own counters
and would need prometheus_client's multiprocess mode.
"""

import os
import re
import time

from prometheus_client import Counter, Histogram, Info, disable_created_metrics, start_http_server
from starlette.routing import compile_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Without this, every counter gets a second series, <name>_created, holding when the
# counter was made. Nothing here uses it; off, there are half as many series.
disable_created_metrics()
BUILD = Info("antifraud_build", "Source revision baked into this image.")
BUILD.info({"version": os.environ.get("BUILD_VERSION", "local")})

REQUESTS = Counter(
    "api_requests_total",
    "HTTP requests answered, by route template and status code.",
    ["method", "route", "status"],
)
LATENCY = Histogram(
    "api_request_duration_seconds",
    "Time from request to the end of the response, by route template.",
    ["method", "route"],
)
RISK_DECISIONS = Counter(
    "api_risk_decisions_total",
    "Risk checks scored (not replays), by decision.",
    ["decision"],
)
for decision in ("approve", "review", "decline"):
    RISK_DECISIONS.labels(decision)     # exist at 0, so "no declines" is a 0, not no data

# A request no route matched - a typo, a scanner trying /wp-admin. One label for all
# of them; their paths are exactly the unbounded set that must never become labels.
UNMATCHED = "unmatched"


class MetricsMiddleware:
    """Times every HTTP request and counts it by method, route template and status.

    Plain ASGI rather than @app.middleware("http"): it sees the status code as the
    response starts, and it still counts a request whose handler raised - as a 500,
    which is what the client gets.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._templates: list[tuple[re.Pattern, str]] | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status = 500                      # unless the response says otherwise
        started = time.perf_counter()

        async def send_and_note_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_note_status)
        finally:
            route = self._route_template(scope)
            method = scope["method"]
            REQUESTS.labels(method, route, str(status)).inc()
            LATENCY.labels(method, route).observe(time.perf_counter() - started)

    def _route_template(self, scope: Scope) -> str:
        # FastAPI's router sets scope["route"] once a route matched; no route, no
        # template - a 404 for a path that is not part of the API
        route = scope.get("route")
        if route is None:
            return UNMATCHED
        if self._templates is None:
            # built on the first request, when every route is registered
            paths = scope["app"].openapi()["paths"]
            self._templates = [(compile_path(template)[0], template) for template in paths]
        for regex, template in self._templates:
            if regex.match(scope["path"]):
                return template
        # a matched route outside the OpenAPI document (/docs, /openapi.json): its
        # path has no parameters, so it is safe as it is
        return getattr(route, "path", UNMATCHED)


def start_server(port: int) -> None:
    if port:
        start_http_server(port)
