"""Payroll runs, results, calculation drill-down, exceptions, payslips, reports."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db, require
from app.api.schemas import ExceptionResolveIn, InputsIn, ReasonIn, RunIn, RunOut
from app.core.security import Perm
from app.db.models import PayrollException, PayrollResultRecord, PayrollRun, Payslip
from app.services import payroll_service as ps
from app.services import reports
from app.services.analytics import exceptions_frame
from app.services.payslips import generate_payslips, render_html, render_pdf
from app.services.reconciliation import reconcile_run

router = APIRouter(tags=["payroll"])


def _run(db: Session, run_id: int) -> PayrollRun:
    run = db.get(PayrollRun, run_id)
    if not run:
        raise HTTPException(404, "Payroll run not found")
    return run


def _wf(fn, *args):
    try:
        return fn(*args)
    except ps.WorkflowError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/payroll-runs", response_model=RunOut)
def create_run(body: RunIn, db: Session = Depends(get_db), user=Depends(require(Perm.PAYROLL_RUN))):
    return _wf(ps.create_run, db, user, body.company_id, body.tax_year, body.frequency, body.payroll_period,
               body.period_start, body.period_end, body.payment_date)


@router.get("/payroll-runs", response_model=list[RunOut])
def list_runs(company_id: int | None = None, db: Session = Depends(get_db), user=Depends(require(Perm.PAYROLL_READ))):
    q = select(PayrollRun).order_by(PayrollRun.payment_date.desc(), PayrollRun.payroll_run_id.desc())
    if company_id:
        q = q.where(PayrollRun.company_id == company_id)
    return list(db.scalars(q))


@router.get("/payroll-runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, db: Session = Depends(get_db), user=Depends(require(Perm.PAYROLL_READ))):
    return _run(db, run_id)


@router.post("/payroll-runs/{run_id}/inputs")
def add_inputs(run_id: int, body: InputsIn, db: Session = Depends(get_db), user=Depends(require(Perm.PAYROLL_RUN))):
    run = _run(db, run_id)
    _wf(ps.set_inputs, db, user, run, body.employee_id, [e.model_dump() for e in body.earnings],
        [d.model_dump() for d in body.deductions])
    return {"status": run.status}


@router.post("/payroll-runs/{run_id}/calculate")
def calculate(run_id: int, db: Session = Depends(get_db), user=Depends(require(Perm.PAYROLL_RUN))):
    run = _run(db, run_id)
    totals = _wf(ps.calculate_run, db, user, run)
    return {"status": run.status, "totals": totals, "seconds": run.calc_seconds}


@router.post("/payroll-runs/{run_id}/validate")
def validate(run_id: int, db: Session = Depends(get_db), user=Depends(require(Perm.PAYROLL_RUN))):
    run = _run(db, run_id)
    df = exceptions_frame(db, run_id)
    counts = df.groupby("severity").size().to_dict() if not df.empty else {}
    return {"status": run.status, "blocking": ps.blocking_exceptions(db, run), "by_severity": counts,
            "reconciliation": reconcile_run(db, run, record=False)}


@router.post("/payroll-runs/{run_id}/approve")
def approve(run_id: int, db: Session = Depends(get_db), user=Depends(require(Perm.PAYROLL_APPROVE))):
    run = _run(db, run_id)
    _wf(ps.approve_run, db, user, run)
    generate_payslips(db, user, run)
    return {"status": run.status}


@router.post("/payroll-runs/{run_id}/reverse", response_model=RunOut)
def reverse(run_id: int, body: ReasonIn, db: Session = Depends(get_db), user=Depends(require(Perm.PAYROLL_APPROVE))):
    return _wf(ps.reverse_run, db, user, _run(db, run_id), body.reason)


@router.get("/payroll-runs/{run_id}/results")
def results(run_id: int, db: Session = Depends(get_db), user=Depends(require(Perm.PAYROLL_READ))):
    df = reports.register(db, _run(db, run_id))
    return reports.records(df)


@router.get("/payroll-results/{result_id}/explain")
def explain(result_id: int, component: str | None = None, db: Session = Depends(get_db),
            user=Depends(require(Perm.PAYROLL_READ))):
    """'Why was this employee's PAYE €x?' - full structured calculation trace."""
    r = db.get(PayrollResultRecord, result_id)
    if not r:
        raise HTTPException(404, "Result not found")
    steps = [t for t in (r.trace or []) if component is None or t["component"] == component.upper()]
    return {"result_id": r.result_id, "status": r.status, "paye": r.paye, "usc": r.usc, "prsi_ee": r.prsi_ee,
            "prsi_er": r.prsi_er, "net_pay": r.net_pay, "rules_used": r.rules_used, "messages": r.messages,
            "error": r.error_message, "trace": steps}


@router.get("/payroll-runs/{run_id}/reconciliation")
def reconciliation(run_id: int, db: Session = Depends(get_db), user=Depends(require(Perm.REPORTS))):
    return reconcile_run(db, _run(db, run_id), record=False)


@router.get("/payroll-runs/{run_id}/journal")
def journal(run_id: int, fmt: str = "json", db: Session = Depends(get_db), user=Depends(require(Perm.REPORTS))):
    run = _run(db, run_id)
    lines = reports.journal(run)
    if fmt == "csv":
        import pandas as pd
        return Response(reports.to_csv(pd.DataFrame(lines)), media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=journal_run{run_id}.csv"})
    return {"balanced": reports.journal_balanced(lines), "lines": lines}


@router.get("/payroll-runs/{run_id}/export.xlsx")
def export_xlsx(run_id: int, db: Session = Depends(get_db), user=Depends(require(Perm.REPORTS))):
    data = reports.run_workbook(db, _run(db, run_id))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=payroll_run{run_id}.xlsx"})


@router.get("/employees/{employee_id}/payslip")
def payslip(employee_id: int, run_id: int | None = None, fmt: str = "html", db: Session = Depends(get_db),
            user=Depends(require(Perm.PAYROLL_READ))):
    q = (select(PayrollResultRecord).join(PayrollRun)
         .where(PayrollResultRecord.employee_id == employee_id, PayrollResultRecord.status == "CALCULATED",
                PayrollRun.status.in_(ps.FINAL_STATUSES))
         .options(selectinload(PayrollResultRecord.result_deductions)).order_by(PayrollRun.payment_date.desc()))
    if run_id:
        q = q.where(PayrollResultRecord.payroll_run_id == run_id)
    r = db.scalars(q).first()
    if not r:
        raise HTTPException(404, "No approved payslip found")
    if fmt == "pdf":
        return Response(render_pdf(db, r), media_type="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename=payslip_{employee_id}_{r.payroll_run_id}.pdf"})
    stored = db.scalar(select(Payslip).where(Payslip.result_id == r.result_id))
    return HTMLResponse(stored.html if stored else render_html(db, r))


@router.get("/exceptions")
def list_exceptions(run_id: int | None = None, severity: str | None = None, status: str | None = None,
                    db: Session = Depends(get_db), user=Depends(require(Perm.PAYROLL_READ))):
    df = exceptions_frame(db, run_id)
    if df.empty:
        return []
    if severity:
        df = df[df["severity"] == severity.upper()]
    if status:
        df = df[df["status"] == status.upper()]
    return reports.records(df)


@router.post("/exceptions/{exception_id}/resolve")
def resolve(exception_id: int, body: ExceptionResolveIn, db: Session = Depends(get_db),
            user=Depends(require(Perm.PAYROLL_RUN))):
    x = db.get(PayrollException, exception_id)
    if not x:
        raise HTTPException(404, "Exception not found")
    _wf(ps.resolve_exception, db, user, x, body.note, body.status)
    return {"exception_id": exception_id, "status": x.status}
