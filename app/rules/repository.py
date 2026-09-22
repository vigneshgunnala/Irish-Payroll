"""Versioned statutory rule repository.

Rules are data, never constants in calculation code. Every rule carries its
source, effective dates and a verification status. The calculation engine asks
the repository for "the <category>.<parameter> rule in force on <date>" and the
repository refuses to hand back anything that is not VERIFIED unless the caller
explicitly opts in (which the payroll engine never does).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"


class RuleError(Exception):
    """Base class for rule lookup problems."""

    code = "RULE_ERROR"


class RuleNotFoundError(RuleError):
    code = "RULE_MISSING"


class UnverifiedRuleError(RuleError):
    code = "RULE_UNVERIFIED"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    rule_set_id: str
    jurisdiction: str
    tax_year: int
    category: str
    parameter: str
    value: Any
    effective_from: date
    effective_to: date | None
    source_authority: str
    source_url: str
    source_document: str
    verified_date: date | None
    status: str
    notes: str = ""

    @property
    def is_verified(self) -> bool:
        return self.status == "VERIFIED"

    @property
    def version_label(self) -> str:
        to = self.effective_to.isoformat() if self.effective_to else "open"
        return f"{self.rule_set_id}:{self.rule_id} ({self.effective_from.isoformat()}..{to})"

    def applies_on(self, on: date) -> bool:
        if on < self.effective_from:
            return False
        return self.effective_to is None or on <= self.effective_to

    def reference(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_set_id,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "source": self.source_authority,
            "source_url": self.source_url,
            "source_document": self.source_document,
            "verified_date": self.verified_date.isoformat() if self.verified_date else None,
            "status": self.status,
        }

    def to_dict(self) -> dict[str, Any]:
        d = self.reference()
        d.update(
            {
                "jurisdiction": self.jurisdiction,
                "tax_year": self.tax_year,
                "category": self.category,
                "parameter": self.parameter,
                "value": self.value,
                "notes": self.notes,
            }
        )
        return d


def _parse_date(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


def parse_rule_file(payload: dict[str, Any]) -> list[Rule]:
    sources = payload.get("sources", {})
    out: list[Rule] = []
    for r in payload["rules"]:
        src = sources.get(r["source"])
        if src is None:
            raise ValueError(f"Rule {r['rule_id']} references unknown source {r['source']}")
        eff_from = _parse_date(r["effective_from"])
        assert eff_from is not None
        out.append(
            Rule(
                rule_id=r["rule_id"],
                rule_set_id=payload["rule_set_id"],
                jurisdiction=payload.get("jurisdiction", "IE"),
                tax_year=int(payload["tax_year"]),
                category=r["category"],
                parameter=r["parameter"],
                value=r["value"],
                effective_from=eff_from,
                effective_to=_parse_date(r.get("effective_to")),
                source_authority=src["authority"],
                source_url=src["url"],
                source_document=src["document"],
                verified_date=_parse_date(r.get("verified_date")),
                status=r.get("status", "UNVERIFIED"),
                notes=r.get("notes", ""),
            )
        )
    return out


@dataclass
class RuleRepository:
    rules: list[Rule] = field(default_factory=list)

    @classmethod
    def from_directory(cls, directory: Path = DATA_DIR) -> RuleRepository:
        rules: list[Rule] = []
        for path in sorted(directory.glob("*.json")):
            rules.extend(parse_rule_file(json.loads(path.read_text(encoding="utf-8"))))
        repo = cls(rules)
        repo.check_integrity()
        return repo

    @classmethod
    def from_rules(cls, rules: Iterable[Rule]) -> RuleRepository:
        repo = cls(list(rules))
        repo.check_integrity()
        return repo

    def check_integrity(self) -> None:
        """No two rules for the same parameter may overlap in time."""
        seen: dict[tuple[str, str], list[Rule]] = {}
        ids: set[str] = set()
        for r in self.rules:
            if r.rule_id in ids:
                raise ValueError(f"Duplicate rule_id {r.rule_id}")
            ids.add(r.rule_id)
            if not r.source_url or not r.source_authority:
                raise ValueError(f"Rule {r.rule_id} has no source")
            seen.setdefault((r.category, r.parameter), []).append(r)
        for key, group in seen.items():
            group.sort(key=lambda x: x.effective_from)
            for a, b in zip(group, group[1:]):
                if a.effective_to is None or a.effective_to >= b.effective_from:
                    raise ValueError(f"Overlapping rules for {key}: {a.rule_id} / {b.rule_id}")

    def get(self, category: str, parameter: str, on: date, allow_unverified: bool = False) -> Rule:
        matches = [
            r for r in self.rules if r.category == category and r.parameter == parameter and r.applies_on(on)
        ]
        if not matches:
            raise RuleNotFoundError(
                f"No {category}.{parameter} rule is configured for {on.isoformat()}. "
                "Unable to calculate reliably."
            )
        rule = matches[0]
        if not rule.is_verified and not allow_unverified:
            raise UnverifiedRuleError(
                f"Rule {rule.rule_id} ({category}.{parameter}) is {rule.status} for {on.isoformat()} "
                f"(source: {rule.source_authority}). It cannot be used for calculation until verified."
            )
        return rule

    def list(self, category: str | None = None, tax_year: int | None = None) -> list[Rule]:
        out = [
            r
            for r in self.rules
            if (category is None or r.category == category) and (tax_year is None or r.tax_year == tax_year)
        ]
        return sorted(out, key=lambda r: (r.category, r.parameter, r.effective_from))

    def by_id(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.rule_id == rule_id:
                return r
        raise RuleNotFoundError(rule_id)


_default: RuleRepository | None = None


def default_repository() -> RuleRepository:
    global _default
    if _default is None:
        _default = RuleRepository.from_directory()
    return _default
