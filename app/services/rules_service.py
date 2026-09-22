"""Keeps the rule tables in the database in step with the versioned JSON rule files and
builds the engine's RuleRepository from the database (the DB is the runtime source of truth)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RULE_TABLES
from app.rules.repository import Rule, RuleRepository
from app.services.audit import audit


def sync_rules(session: Session, repo: RuleRepository | None = None, user=None) -> int:
    repo = repo or RuleRepository.from_directory()
    n = 0
    for r in repo.rules:
        table = RULE_TABLES[r.category]
        row = session.get(table, r.rule_id)
        data: dict[str, Any] = dict(
            rule_set_id=r.rule_set_id, jurisdiction=r.jurisdiction, tax_year=r.tax_year, category=r.category,
            parameter=r.parameter, value=r.value, effective_from=r.effective_from, effective_to=r.effective_to,
            source_authority=r.source_authority, source_url=r.source_url, source_document=r.source_document,
            verified_date=r.verified_date, status=r.status, notes=r.notes,
        )
        if row is None:
            session.add(table(rule_id=r.rule_id, **data))
            n += 1
        else:
            before = {"value": row.value, "status": row.status}
            changed = False
            for k, v in data.items():
                if getattr(row, k) != v:
                    setattr(row, k, v)
                    changed = True
            if changed:
                audit(session, user, "RULE_CHANGED", "rule", r.rule_id, before, {"value": r.value, "status": r.status},
                      "Synchronised from versioned rule file")
                n += 1
    session.flush()
    return n


def repository_from_db(session: Session) -> RuleRepository:
    rules: list[Rule] = []
    for table in set(RULE_TABLES.values()):
        for row in session.scalars(select(table)):
            rules.append(Rule(
                rule_id=row.rule_id, rule_set_id=row.rule_set_id, jurisdiction=row.jurisdiction, tax_year=row.tax_year,
                category=row.category, parameter=row.parameter, value=row.value, effective_from=row.effective_from,
                effective_to=row.effective_to, source_authority=row.source_authority, source_url=row.source_url,
                source_document=row.source_document, verified_date=row.verified_date, status=row.status,
                notes=row.notes or "",
            ))
    return RuleRepository.from_rules(rules)


def set_rule_status(session: Session, rule_id: str, status: str, user, reason: str,
                    verified_on: date | None = None) -> None:
    """System admin can (un)verify a rule - always audited with a reason."""
    if status not in {"VERIFIED", "UNVERIFIED", "SUPERSEDED"}:
        raise ValueError("invalid status")
    if not reason:
        raise ValueError("A reason is required to change a rule's verification status")
    for table in set(RULE_TABLES.values()):
        row = session.get(table, rule_id)
        if row is not None:
            before = {"status": row.status, "verified_date": str(row.verified_date)}
            row.status = status
            if status == "VERIFIED":
                row.verified_date = verified_on or date.today()
            audit(session, user, "RULE_STATUS_CHANGED", "rule", rule_id, before,
                  {"status": status, "verified_date": str(row.verified_date)}, reason)
            return
    raise KeyError(rule_id)
