"""Check the provisioned monitoring stack while the CI generator is still running."""

import argparse
import base64
import json
import os
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

DASHBOARDS = {f"antifraud-{name}" for name in ("ops", "fraud", "scoring", "money")}
ALERTS = {
    "high-severity-detection", "big-payout-mismatch", "shared-device", "service-down",
    "rules-runner-stale", "generator-behind", "api-errors", "api-slow", "detection-rate-shift",
}
TARGETS = {"generator", "api", "rules", "prometheus"}


def get_json(url, authorization=None):
    headers = {"Authorization": authorization} if authorization else {}
    with urlopen(Request(url, headers=headers), timeout=5) as response:
        return json.load(response)


def check(grafana, prometheus, authorization):
    dashboards = get_json(f"{grafana}/api/search?type=dash-db", authorization)
    found = {item["uid"] for item in dashboards}
    if found != DASHBOARDS:
        raise ValueError(f"dashboard UIDs: expected {sorted(DASHBOARDS)}, got {sorted(found)}")

    alerts = get_json(f"{grafana}/api/v1/provisioning/alert-rules", authorization)
    found = {item["uid"] for item in alerts}
    if found != ALERTS:
        raise ValueError(f"alert UIDs: expected {sorted(ALERTS)}, got {sorted(found)}")

    response = get_json(f"{prometheus}/api/v1/targets?state=active")
    if response["status"] != "success":
        raise ValueError(f"Prometheus target query failed: {response}")
    targets = response["data"]["activeTargets"]
    found = {item["labels"]["job"] for item in targets}
    if found != TARGETS or len(targets) != len(TARGETS):
        raise ValueError(f"expected exactly four scrape targets, got {targets}")
    unhealthy = [f"{item['labels']['job']}: {item['health']} {item.get('lastError', '')}"
                 for item in targets if item["health"] != "up"]
    if unhealthy:
        raise ValueError(f"targets not UP: {unhealthy}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grafana", default="http://127.0.0.1:3000")
    parser.add_argument("--prometheus", default="http://127.0.0.1:9090")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    credentials = f"admin:{os.environ['GRAFANA_ADMIN_PASSWORD']}".encode()
    authorization = "Basic " + base64.b64encode(credentials).decode()
    deadline = time.monotonic() + args.timeout
    while True:
        try:
            check(args.grafana.rstrip("/"), args.prometheus.rstrip("/"), authorization)
            print("PASS monitoring: 4 dashboards, 9 alert rules, all 4 Prometheus targets UP")
            return
        except (URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
            if time.monotonic() >= deadline:
                raise SystemExit(f"FAIL monitoring: {exc}") from exc
            print(f"Waiting for monitoring: {exc}", flush=True)
            time.sleep(min(3, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    main()
