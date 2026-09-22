"""Rules, analytics, Revenue submission preparation, audit log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require
from app.api.schemas import ReasonIn
from app.core.security import Perm
from app.db.models import AuditLog, PayrollRun, RevenueSubmission
from app.services import analytics
from app.services.payroll_service import WorkflowError, mark_submitted
from app.services.revenue import export_json, prepare_submission
from app.services.rules_service import repository_from_db, set_rule_status

router = APIRouter()


def _rules(db: Session, category: str) -> list[dict]:
    repo = repository_from_db(db)
    return [r.to_dict() for r in repo.list() if r.category in (category.split(","))]


@router.get("/rules/tax", tags=["rules"])
def tax_rules(db: Session = Depends(get_db), user=Depends(require(Perm.RULES_READ))):
    return _rules(db, "PAYE,EMERGENCY")


@router.get("/rules/usc", tags=["rules"])
def usc_rules(db: Session = Depends(get_db), user=Depends(require(Perm.RULES_READ))):
    return _rules(db, "USC")


@router.get("/rules/prsi", tags=["rules"])
def prsi_rules(db: Session = Depends(get_db), user=Depends(require(Perm.RULES_READ))):
    return _rules(db, "PRSI")


@router.get("/rules", tags=["rules"])
def all_rules(db: Session = Depends(get_db), user=Depends(require(Perm.RULES_READ))):
    return [r.to_dict() for r in repository_from_db(db).list()]


@router.post("/rules/{rule_id}/status", tags=["rules"])
def rule_status(rule_id: str, status: str, body: ReasonIn, db: Session = Depends(get_db),
                user=Depends(require(Perm.RULES_WRITE))):
    try:
        set_rule_status(db, rule_id, status, user, body.reason)
    except KeyError:
        raise HTTPException(404, "Rule not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"rule_id": rule_id, "status": status}


@router.get("/analytics/payroll", tags=["analytics"])
def payroll_analytics(company_id: int, tax_year: int = 2026, period: int | None = None, db: Session = Depends(get_db),
                      user=Depends(require(Perm.ANALYTICS))):
    df = analytics.results_frame(db, company_id, tax_year)
    if df.empty:
        return {"trend": [], "departments": []}
    period = period or int(df["period"].max())
    from app.services.reports import records as clean
    return {"period": period, "trend": clean(analytics.trend(df)),
            "departments": clean(analytics.by_department(df, period)), "variance": clean(analytics.variance(df, period))}


@router.post("/revenue/submission/prepare", tags=["revenue"])
def revenue_prepare(run_id: int, db: Session = Depends(get_db), user=Depends(require(Perm.REVENUE_PREPARE))):
    run = db.get(PayrollRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    try:
        sub = prepare_submission(db, user, run)
        if sub.status == "PREPARED" and run.status == "APPROVED":
            mark_submitted(db, user, run)
    except (ValueError, WorkflowError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"submission_id": sub.submission_id, "ref": sub.submission_ref, "status": sub.status,
            "validation_errors": sub.validation_errors, "lines": len(sub.payload["payslips"])}


@router.get("/revenue/submission/{submission_id}/export", tags=["revenue"])
def revenue_export(submission_id: int, db: Session = Depends(get_db), user=Depends(require(Perm.REVENUE_PREPARE))):
    sub = db.get(RevenueSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    return Response(export_json(sub), media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename={sub.submission_ref}.json"})


@router.get("/audit", tags=["audit"])
def audit_log(limit: int = 200, action: str | None = None, db: Session = Depends(get_db),
              user=Depends(require(Perm.AUDIT_READ))):
    q = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)
    if action:
        q = q.where(AuditLog.action == action)
    return [{"timestamp": a.timestamp, "user": a.user_email, "action": a.action, "entity": a.entity,
             "entity_id": a.entity_id, "before": a.before_value, "after": a.after_value, "reason": a.reason}
            for a in db.scalars(q)]
