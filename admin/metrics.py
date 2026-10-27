"""Build identity only, on an internal port owned by the Gunicorn master."""

import os

from prometheus_client import CollectorRegistry, Info, start_http_server


def start():
    port = int(os.environ.get("METRICS_PORT", "0") or 0)
    if port:
        registry = CollectorRegistry()
        Info("antifraud_build", "Source revision baked into this image.", registry=registry).info(
            {"version": os.environ.get("BUILD_VERSION", "local")}
        )
        return start_http_server(port, registry=registry)
    return None
