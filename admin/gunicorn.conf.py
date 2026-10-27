"""Start one metrics listener, not one listener per Flask worker."""

import metrics


def when_ready(server):
    metrics.start()
