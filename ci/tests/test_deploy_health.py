"""Deployment must not record success until live readiness and versions agree."""

import time

import pytest
from deploy import healthcheck

VERSION = "a" * 40
TARGET_URL = "http://prometheus:9090/api/v1/targets?state=active"
BUILD_URL = healthcheck.BUILD_QUERY


@pytest.fixture
def responses(monkeypatch):
    data = {
        "http://127.0.0.1:8000/ready": {"status": "ready"},
        "http://admin:5000/health": {"status": "ok"},
        "http://grafana:3000/api/health": {"database": "ok"},
        TARGET_URL: {"status": "success", "data": {"activeTargets": [
            {"labels": {"job": job}, "health": "up"}
            for job in healthcheck.SERVICES | {"prometheus"}
        ]}},
        BUILD_URL: {"status": "success", "data": {"result": [
            {"metric": {"job": job, "version": VERSION}, "value": [0, str(time.time())]}
            for job in healthcheck.SERVICES
        ]}},
    }
    monkeypatch.setattr(healthcheck, "get_json", lambda url: data[url])
    return data


def test_ready_services_at_expected_version_pass(responses):
    healthcheck.check(VERSION)


def test_missing_target_fails(responses):
    responses[TARGET_URL]["data"]["activeTargets"].pop()
    with pytest.raises(ValueError, match="five Prometheus targets UP"):
        healthcheck.check(VERSION)


def test_down_target_fails(responses):
    responses[TARGET_URL]["data"]["activeTargets"][0]["health"] = "down"
    with pytest.raises(ValueError, match="five Prometheus targets UP"):
        healthcheck.check(VERSION)


def test_old_and_new_versions_together_do_not_pass(responses):
    responses[BUILD_URL]["data"]["result"][0]["metric"]["version"] = "b" * 40
    with pytest.raises(ValueError, match="not every service reports"):
        healthcheck.check(VERSION)


def test_missing_build_metric_fails(responses):
    responses[BUILD_URL]["data"]["result"].pop()
    with pytest.raises(ValueError, match="one build version"):
        healthcheck.check(VERSION)


def test_stale_samples_do_not_pass_even_with_the_expected_version(responses):
    responses[BUILD_URL]["data"]["result"][0]["value"][1] = str(time.time() - 120)
    with pytest.raises(ValueError, match="more than 60 seconds old"):
        healthcheck.check(VERSION)
