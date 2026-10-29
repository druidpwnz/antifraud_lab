"""Runs inside the API container: readiness, scrape health and matching build versions."""

import json
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

SERVICES = {"api", "admin", "rules", "generator"}
BUILD_QUERY = "http://prometheus:9090/api/v1/query?" + urlencode({
    # A Prometheus restart can retain old versions until lookback expiry. Pick
    # the newest sample per job, rather than filtering away an unexpected version.
    "query": "topk by (job) (1, timestamp(antifraud_build_info))",
})


def get_json(url):
    with urlopen(url, timeout=3) as response:
        return json.load(response)


def check(version):
    get_json("http://127.0.0.1:8000/ready")
    get_json("http://admin:5000/health")
    get_json("http://grafana:3000/api/health")
    targets = get_json("http://prometheus:9090/api/v1/targets?state=active")
    if targets["status"] != "success":
        raise ValueError("Prometheus target query failed")
    targets = targets["data"]["activeTargets"]
    if ({target["labels"]["job"] for target in targets} != SERVICES | {"prometheus"}
            or len(targets) != 5 or any(target["health"] != "up" for target in targets)):
        raise ValueError("expected all five Prometheus targets UP")
    builds = get_json(BUILD_QUERY)
    if builds["status"] != "success":
        raise ValueError("Prometheus build query failed")
    builds = builds["data"]["result"]
    if {item["metric"]["job"] for item in builds} != SERVICES or len(builds) != 4:
        raise ValueError("expected one build version for each of the four services")
    if any(item["metric"].get("version") != version for item in builds):
        raise ValueError(f"not every service reports {version}")
    if any(time.time() - float(item["value"][1]) > 60 for item in builds):
        raise ValueError("service build samples are more than 60 seconds old")


if __name__ == "__main__":
    try:
        check(sys.argv[1])
        print(f"PASS readiness, five scrape targets, four services at {sys.argv[1]}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"Health check: {exc}") from exc
