"""Audit trail. Values are sanitised so PPSNs / bank details never land in the log verbatim."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import mask_iban, mask_ppsn
from app.db.models import AuditLog

SENSITIVE = {"ppsn": mask_ppsn, "bank_iban_masked": mask_iban, "password": lambda _: "[REDACTED]",
             "password_hash": lambda _: "[REDACTED]"}


def _clean(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: (SENSITIVE[k](x) if k in SENSITIVE else _clean(x)) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def audit(session: Session, user, action: str, entity: str, entity_id: Any = None,
          before: dict | None = None, after: dict | None = None, reason: str | None = None) -> AuditLog:
    row = AuditLog(
        user_id=getattr(user, "user_id", None),
        user_email=getattr(user, "email", None) or ("system" if user is None else None),
        action=action, entity=entity, entity_id=str(entity_id) if entity_id is not None else None,
        before_value=_clean(before) if before else None, after_value=_clean(after) if after else None, reason=reason,
    )
    session.add(row)
    return row
