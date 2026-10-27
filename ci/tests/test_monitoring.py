"""A missing scrape target or provisioned object must not make CI green."""

import pytest
from ci import check_monitoring as monitoring


@pytest.fixture
def responses(monkeypatch):
    data = {
        "/api/search?type=dash-db": [{"uid": uid} for uid in monitoring.DASHBOARDS],
        "/api/v1/provisioning/alert-rules": [{"uid": uid} for uid in monitoring.ALERTS],
        "/api/v1/targets?state=active": {
            "status": "success",
            "data": {"activeTargets": [{"labels": {"job": job}, "health": "up"}
                                       for job in sorted(monitoring.TARGETS)]},
        },
        "/api/v1/query?query=antifraud_build_info": {
            "status": "success",
            "data": {"result": [{"metric": {"job": job, "version": "local"}, "value": [0, "1"]}
                                for job in sorted(monitoring.SERVICES)]},
        },
    }
    monkeypatch.setattr(monitoring, "get_json", lambda url, authorization=None: data[url])
    return data


def test_complete_healthy_monitoring_passes(responses):
    monitoring.check("", "", "test")


@pytest.mark.parametrize("endpoint", ["/api/search?type=dash-db", "/api/v1/provisioning/alert-rules"])
def test_missing_provisioned_object_fails(responses, endpoint):
    responses[endpoint].pop()
    with pytest.raises(ValueError, match="UIDs"):
        monitoring.check("", "", "test")


def test_no_scrape_targets_is_not_success(responses):
    responses["/api/v1/targets?state=active"]["data"]["activeTargets"] = []
    with pytest.raises(ValueError, match="exactly 5 scrape targets"):
        monitoring.check("", "", "test")


def test_missing_generator_target_fails_even_if_others_are_up(responses):
    targets = responses["/api/v1/targets?state=active"]["data"]["activeTargets"]
    targets[:] = [target for target in targets if target["labels"]["job"] != "generator"]
    with pytest.raises(ValueError, match="exactly 5 scrape targets"):
        monitoring.check("", "", "test")


def test_down_target_fails(responses):
    responses["/api/v1/targets?state=active"]["data"]["activeTargets"][0]["health"] = "down"
    with pytest.raises(ValueError, match="targets not UP"):
        monitoring.check("", "", "test")


def test_failed_prometheus_query_fails(responses):
    responses["/api/v1/targets?state=active"]["status"] = "error"
    with pytest.raises(ValueError, match="target query failed"):
        monitoring.check("", "", "test")


def test_wrong_service_version_fails(responses):
    with pytest.raises(ValueError, match="expected build version"):
        monitoring.check("", "", "test", version="a" * 40)


def test_missing_admin_version_fails(responses):
    builds = responses["/api/v1/query?query=antifraud_build_info"]["data"]["result"]
    builds[:] = [item for item in builds if item["metric"]["job"] != "admin"]
    with pytest.raises(ValueError, match="missing or duplicate service build versions"):
        monitoring.check("", "", "test")


def test_expected_commit_version_passes(responses):
    for item in responses["/api/v1/query?query=antifraud_build_info"]["data"]["result"]:
        item["metric"]["version"] = "a" * 40
    monitoring.check("", "", "test", version="a" * 40)
