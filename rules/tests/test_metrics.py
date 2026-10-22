"""The runner's metrics: labelled by rule only, and present before anything happened."""

from prometheus_client import REGISTRY

import runner


def sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels)


def test_every_rule_has_its_series_at_start():
    # a counter never touched has no series - "no LATE_BET alerts today" would be
    # no data instead of 0
    for rule in runner.RULES:
        assert sample("rules_alerts_created_total", rule_code=rule.code, severity=rule.severity) is not None
        assert sample("rules_rows_scanned_total", rule_code=rule.code) is not None
    for outcome in ("ok", "failed"):
        assert sample("rules_runs_total", outcome=outcome) is not None


def test_record_counts_alerts_and_rows_under_the_rules_code():
    rule = runner.RULES[0]
    before_alerts = sample("rules_alerts_created_total", rule_code=rule.code, severity=rule.severity)
    before_rows = sample("rules_rows_scanned_total", rule_code=rule.code)
    runner.record(rule, runner.Result(rule.code, scanned=120, created=3, upto=500))
    assert sample("rules_alerts_created_total", rule_code=rule.code, severity=rule.severity) - before_alerts == 3
    assert sample("rules_rows_scanned_total", rule_code=rule.code) - before_rows == 120


def test_labels_are_only_rule_codes_and_severities():
    codes = {rule.code for rule in runner.RULES}
    for family in REGISTRY.collect():
        if not family.name.startswith("rules_"):
            continue
        for s in family.samples:
            assert set(s.labels) <= {"rule_code", "severity", "outcome", "le"}, s
            if "rule_code" in s.labels:
                assert s.labels["rule_code"] in codes
