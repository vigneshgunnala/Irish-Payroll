"""Rule store integrity: every statutory value has a source, dates never overlap, UNVERIFIED rules are unusable."""

import json
from datetime import date

import pytest

from app.rules.repository import DATA_DIR, Rule, RuleNotFoundError, RuleRepository, UnverifiedRuleError

REQUIRED = {"rule_id", "category", "parameter", "value", "effective_from", "effective_to", "source", "verified_date",
            "status", "notes"}


def test_every_rule_has_full_metadata():
    for path in DATA_DIR.glob("*.json"):
        payload = json.loads(path.read_text())
        assert payload["jurisdiction"] == "IE"
        for r in payload["rules"]:
            assert REQUIRED <= r.keys(), r["rule_id"]
            src = payload["sources"][r["source"]]
            assert src["url"].startswith("https://") and src["authority"] and src["document"]
            assert r["notes"], f"{r['rule_id']} needs notes/evidence"


def test_only_official_sources_are_verified(repo):
    official = ("https://www.revenue.ie/", "https://assets.gov.ie/", "https://www.gov.ie/")
    for r in repo.rules:
        if r.is_verified:
            assert r.source_url.startswith(official), f"{r.rule_id} verified from non-official source {r.source_url}"


def test_unverified_rule_refused(repo):
    from dataclasses import replace
    rules = [replace(r, status="UNVERIFIED") if r.rule_id == "PRSI-2026-B-H2" else r for r in repo.rules]
    gated = RuleRepository.from_rules(rules)
    with pytest.raises(UnverifiedRuleError):
        gated.get("PRSI", "class_B", date(2026, 10, 5))
    assert gated.get("PRSI", "class_B", date(2026, 10, 5), allow_unverified=True).rule_id == "PRSI-2026-B-H2"


def test_oct_2026_rates_for_all_classes_from_sw14(repo):
    on = date(2026, 10, 1)
    assert repo.get("PRSI", "class_J", on).value["employer_rate"] == "0.0085"
    for k, er in (("B", "0.0236"), ("C", "0.022"), ("D", "0.027")):
        v = repo.get("PRSI", f"class_{k}", on).value
        assert (v["employee_lower_rate"], v["employee_higher_rate"], v["employer_rate"]) == ("0.0125", "0.0435", er)


def test_missing_rule_refused(repo):
    with pytest.raises(RuleNotFoundError):
        repo.get("PRSI", "class_A", date(2027, 1, 5))


def test_rule_selected_by_effective_date(repo):
    assert repo.get("PRSI", "class_A", date(2026, 9, 30)).rule_id == "PRSI-2026-A-H1"
    assert repo.get("PRSI", "class_A", date(2026, 10, 1)).rule_id == "PRSI-2026-A-H2"


def test_overlapping_rules_rejected(repo):
    base = repo.by_id("USC-2026-BANDS")
    clash = Rule(**{**base.__dict__, "rule_id": "X", "effective_from": date(2026, 6, 1)})
    with pytest.raises(ValueError, match="Overlapping"):
        RuleRepository.from_rules([base, clash])


def test_2026_values_match_official_figures(repo):
    d = date(2026, 5, 1)
    assert repo.get("PAYE", "standard_rate", d).value == "0.20"
    assert repo.get("PAYE", "srcop_single", d).value == "44000"
    assert [b["upper"] for b in repo.get("USC", "standard_bands", d).value] == ["12012", "28700", "70044", None]
    a = repo.get("PRSI", "class_A", d).value
    assert (a["employee_rate"], a["employer_lower_rate"], a["employer_higher_rate"], a["employer_lower_up_to_weekly"]) == \
        ("0.042", "0.09", "0.1125", "552")
    assert repo.get("EMERGENCY", "srcop_weekly_weeks_1_4", d).value == "846.16"
