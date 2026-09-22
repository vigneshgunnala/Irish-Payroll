"""Payroll run workflow: create → inputs → calculate (bulk) → validate → approve → submit prep → complete.

Status machine
    DRAFT → CALCULATING → VALIDATION_REQUIRED | READY_FOR_APPROVAL → APPROVED → SUBMITTED → COMPLETED
    APPROVED / SUBMITTED / COMPLETED → REVERSED (with reason; a CORRECTION run then replaces it)
"""

from __future__ import annotations

import csv
import io
import time
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.models import (
    Employee,
    PayrollDeduction,
    PayrollEarning,
    PayrollException,
    PayrollInputRecord,
    PayrollResultRecord,
    PayrollRun,
)
from app.engine.calculator import PayrollEngine
from app.engine.money import ZERO, D, money
from app.engine.types import (
    BenefitLine,
    BenefitType,
    CalcStatus,
    Deduction,
    EarningLine,
    EarningType,
    PayFrequency,
    PayrollInput,
    PensionContribution,
    PensionScheme,
    YearToDate,
)
from app.services.audit import audit
from app.services.employees import standard_pay, to_engine_profile
from app.services.rules_service import repository_from_db

FINAL_STATUSES = ("APPROVED", "SUBMITTED", "COMPLETED")
EDITABLE = ("DRAFT", "VALIDATION_REQUIRED", "READY_FOR_APPROVAL")
TOTAL_FIELDS = ("gross_pay", "bik", "paye", "usc", "prsi_ee", "prsi_er", "lpt", "pension_ee", "pension_er",
                "other_deductions", "net_pay", "employer_cost", "statutory_liability")


class WorkflowError(Exception):
    pass


# ------------------------------------------------------------------ create & inputs


def create_run(session: Session, user, company_id: int, tax_year: int, frequency: str, period: int,
               period_start: date, period_end: date, payment_date: date, run_type: str = "REGULAR",
               reverses_run_id: int | None = None) -> PayrollRun:
    if payment_date.year != tax_year:
        raise WorkflowError("Payment date must fall in the tax year (Revenue taxes pay by pay date).")
    if period_end < period_start:
        raise WorkflowError("Period end is before period start.")
    if run_type == "REGULAR":
        dup = session.scalar(select(PayrollRun).where(
            PayrollRun.company_id == company_id, PayrollRun.tax_year == tax_year, PayrollRun.frequency == frequency,
            PayrollRun.payroll_period == period, PayrollRun.run_type == "REGULAR", PayrollRun.status != "REVERSED"))
        if dup:
            raise WorkflowError(f"A payroll run already exists for {frequency} period {period}/{tax_year} (run {dup.payroll_run_id}).")
    run = PayrollRun(company_id=company_id, tax_year=tax_year, frequency=frequency, payroll_period=period,
                     period_start=period_start, period_end=period_end, payment_date=payment_date, status="DRAFT",
                     run_type=run_type, reverses_run_id=reverses_run_id, created_by=getattr(user, "user_id", None))
    session.add(run)
    session.flush()
    audit(session, user, "PAYROLL_RUN_CREATED", "payroll_run", run.payroll_run_id, None,
          {"period": period, "tax_year": tax_year, "frequency": frequency, "payment_date": payment_date, "type": run_type})
    return run


def _require_editable(run: PayrollRun) -> None:
    if run.status not in EDITABLE:
        raise WorkflowError(f"Run {run.payroll_run_id} is {run.status} and locked.")


def set_inputs(session: Session, user, run: PayrollRun, employee_id: int, earnings: list[dict[str, Any]],
               deductions: list[dict[str, Any]] | None = None, replace: bool = True) -> PayrollInputRecord:
    _require_editable(run)
    rec = session.scalar(select(PayrollInputRecord).where(PayrollInputRecord.payroll_run_id == run.payroll_run_id,
                                                          PayrollInputRecord.employee_id == employee_id))
    if rec is None:
        rec = PayrollInputRecord(payroll_run_id=run.payroll_run_id, employee_id=employee_id)
        session.add(rec)
        session.flush()
    if replace:
        rec.earnings.clear()
        rec.deductions.clear()
    for e in earnings:
        EarningType(e["type"])  # validate
        rec.earnings.append(PayrollEarning(earning_type=e["type"], description=e.get("description"),
                                           hours=e.get("hours"), rate=e.get("rate"), amount=money(e["amount"])))
    for d in deductions or []:
        rec.deductions.append(PayrollDeduction(code=d["code"], description=d.get("description"), amount=money(d["amount"])))
    if run.status != "DRAFT":
        run.status = "DRAFT"  # inputs changed → must recalculate
    return rec


def import_inputs_csv(session: Session, user, run: PayrollRun, content: str) -> dict[str, Any]:
    """CSV: employee_number,type,amount[,description,hours]  - type is an EarningType or DEDUCTION:<code>."""
    _require_editable(run)
    emps = {e.employee_number: e.employee_id for e in session.scalars(
        select(Employee).where(Employee.company_id == run.company_id))}
    grouped: dict[int, dict[str, list]] = {}
    errors = []
    for i, row in enumerate(csv.DictReader(io.StringIO(content)), start=2):
        eid = emps.get((row.get("employee_number") or "").strip())
        if eid is None:
            errors.append({"line": i, "error": f"Unknown employee {row.get('employee_number')}"})
            continue
        try:
            amt = D(row["amount"])
            t = row["type"].strip().upper()
            g = grouped.setdefault(eid, {"earnings": [], "deductions": []})
            if t.startswith("DEDUCTION:"):
                g["deductions"].append({"code": t.split(":", 1)[1], "amount": amt, "description": row.get("description")})
            else:
                EarningType(t)
                g["earnings"].append({"type": t, "amount": amt, "description": row.get("description"),
                                      "hours": D(row["hours"]) if row.get("hours") else None})
        except Exception as exc:  # noqa: BLE001
            errors.append({"line": i, "error": str(exc)})
    for eid, g in grouped.items():
        set_inputs(session, user, run, eid, g["earnings"], g["deductions"], replace=False)
    audit(session, user, "PAYROLL_INPUTS_IMPORTED", "payroll_run", run.payroll_run_id, None,
          {"employees": len(grouped), "errors": len(errors)})
    return {"employees": len(grouped), "errors": errors}


# ------------------------------------------------------------------ calculation


def _ytd_from_json(d: dict[str, Any] | None) -> YearToDate:
    if not d:
        return YearToDate()
    y = YearToDate()
    for k, v in d.items():
        if hasattr(y, k):
            setattr(y, k, int(v) if k in ("small_benefit_count", "emergency_periods") else D(v))
    return y


def _ytd_to_json(y: YearToDate) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in asdict(y).items()}


def prior_results(session: Session, run: PayrollRun) -> dict[int, PayrollResultRecord]:
    """Latest finalised result per employee earlier in the same tax year (one query)."""
    q = (select(PayrollResultRecord).join(PayrollRun)
         .where(PayrollRun.company_id == run.company_id, PayrollRun.tax_year == run.tax_year,
                PayrollRun.frequency == run.frequency, PayrollRun.status.in_(FINAL_STATUSES),
                PayrollRun.payroll_run_id != run.payroll_run_id,
                PayrollRun.payroll_period <= run.payroll_period,
                PayrollResultRecord.status == CalcStatus.CALCULATED.value)
         .order_by(PayrollRun.payroll_period.desc(), PayrollRun.payroll_run_id.desc()))
    out: dict[int, PayrollResultRecord] = {}
    for r in session.scalars(q):
        # a correction run for the same period replaces, it does not add to, the period it corrects
        if run.run_type == "CORRECTION" and r.payroll_run_id == run.reverses_run_id:
            continue
        out.setdefault(r.employee_id, r)
    return out


def _prorate(emp: Employee, run: PayrollRun, amount: Decimal) -> tuple[Decimal, str | None]:
    start = max(emp.employment_start_date, run.period_start)
    end = min(emp.employment_end_date or run.period_end, run.period_end)
    total_days = (run.period_end - run.period_start).days + 1
    worked = (end - start).days + 1
    if worked >= total_days:
        return amount, None
    if worked <= 0:
        return ZERO, "not employed in period"
    return money(amount * Decimal(worked) / Decimal(total_days)), f"pro-rata {worked}/{total_days} days"


def eligible_employees(session: Session, run: PayrollRun) -> list[Employee]:
    q = (select(Employee).where(
        Employee.company_id == run.company_id, Employee.pay_frequency == run.frequency,
        Employee.employment_start_date <= run.period_end,
        (Employee.employment_end_date.is_(None)) | (Employee.employment_end_date >= run.period_start))
        .options(selectinload(Employee.tax_profile), selectinload(Employee.benefits), selectinload(Employee.department))
        .order_by(Employee.employee_number))
    return list(session.scalars(q))


def build_input(emp: Employee, run: PayrollRun, rec: PayrollInputRecord | None, prior: PayrollResultRecord | None) -> PayrollInput:
    earnings: list[EarningLine] = []
    lines = list(rec.earnings) if rec else []
    if not any(line.earning_type in ("BASIC", "HOURLY") for line in lines):
        base = standard_pay(emp, run.frequency)
        base, note = _prorate(emp, run, base)
        kind = EarningType.BASIC if emp.salary_type == "SALARY" else EarningType.HOURLY
        desc = "Basic salary" if kind == EarningType.BASIC else "Hourly wages"
        earnings.append(EarningLine(kind, base, desc + (f" ({note})" if note else "")))
    for line in lines:
        earnings.append(EarningLine(EarningType(line.earning_type), D(line.amount), line.description or "",
                                    D(line.hours) if line.hours is not None else None))
    basic_total = sum((e.amount for e in earnings if e.type in (EarningType.BASIC, EarningType.HOURLY)), ZERO)

    pensions = []
    if emp.pension_scheme:
        pensions.append(PensionContribution(PensionScheme(emp.pension_scheme),
                                            money(basic_total * D(emp.pension_ee_percent or 0)),
                                            money(basic_total * D(emp.pension_er_percent or 0))))
    benefits = []
    for b in emp.benefits:
        if b.active_from and b.active_from > run.period_end:
            continue
        if b.active_to and b.active_to < run.period_start:
            continue
        benefits.append(BenefitLine(BenefitType(b.benefit_type), b.description or "", omv=b.omv, co2_g_km=b.co2_g_km,
                                    business_km=b.business_km,
                                    employee_contribution_annual=D(b.employee_contribution_annual or 0),
                                    annual_value=b.annual_value, period_value=b.period_value, value=b.period_value))
    deductions = [Deduction(d.code, D(d.amount), d.description or "") for d in (rec.deductions if rec else [])]
    return PayrollInput(
        employee_ref=emp.employee_number, tax_year=run.tax_year, frequency=PayFrequency(run.frequency),
        period_number=run.payroll_period, payment_date=run.payment_date, prsi_class=emp.prsi_class,
        tax_profile=to_engine_profile(emp), ytd=_ytd_from_json(prior.ytd if prior else None), earnings=earnings,
        benefits=benefits, pensions=pensions, deductions=deductions, date_of_birth=emp.date_of_birth,
        insurable_weeks=rec.insurable_weeks if rec else None,
    )


def calculate_run(session: Session, user, run: PayrollRun, engine: PayrollEngine | None = None) -> dict[str, Any]:
    _require_editable(run)
    t0 = time.perf_counter()
    recalculation = run.calculated_at is not None
    run.status = "CALCULATING"
    session.flush()
    engine = engine or PayrollEngine(repository_from_db(session))

    session.execute(delete(PayrollResultRecord).where(PayrollResultRecord.payroll_run_id == run.payroll_run_id))
    session.execute(delete(PayrollException).where(PayrollException.payroll_run_id == run.payroll_run_id))
    session.flush()

    employees = eligible_employees(session, run)
    inputs = {r.employee_id: r for r in session.scalars(
        select(PayrollInputRecord).where(PayrollInputRecord.payroll_run_id == run.payroll_run_id)
        .options(selectinload(PayrollInputRecord.earnings), selectinload(PayrollInputRecord.deductions)))}
    priors = prior_results(session, run)
    unknown_inputs = set(inputs) - {e.employee_id for e in employees}

    ok = errors = review = 0
    totals = {k: ZERO for k in TOTAL_FIELDS}
    for emp in employees:
        inp = build_input(emp, run, inputs.get(emp.employee_id), priors.get(emp.employee_id))
        res = engine.calculate(inp)
        row = PayrollResultRecord(
            payroll_run_id=run.payroll_run_id, employee_id=emp.employee_id, status=res.status.value,
            **{k: getattr(res, k) for k in res.MONEY_FIELDS},
            prsi_class=res.prsi_class, prsi_subclass=res.prsi_subclass, insurable_weeks=res.insurable_weeks,
            tax_basis_applied=res.tax_basis_applied, usc_status_applied=res.usc_status_applied,
            ytd=_ytd_to_json(res.new_ytd) if res.new_ytd else None, trace=res.trace_dicts(), messages=res.messages,
            rules_used=res.rules_used, earnings_detail=[{**e, "amount": str(e["amount"])} for e in res.earnings],
            error_code=res.error_code, error_message=res.error_message,
        )
        for d in res.deductions:
            row.result_deductions.append(PayrollDeduction(code=d["code"], description=d["description"],
                                                          amount=max(d["amount"], ZERO)))
        session.add(row)
        if res.status != CalcStatus.CALCULATED:
            errors += 1
        else:
            ok += 1
            for k in TOTAL_FIELDS:
                totals[k] += getattr(res, k)
        if res.messages:
            review += 1 if res.status == CalcStatus.CALCULATED else 0
        for m in res.messages:
            session.add(PayrollException(payroll_run_id=run.payroll_run_id, employee_id=emp.employee_id,
                                         source="ENGINE", code=m["code"], severity=m["severity"], message=m["message"]))
    for eid in unknown_inputs:
        session.add(PayrollException(payroll_run_id=run.payroll_run_id, employee_id=eid, source="VALIDATION",
                                     code="INPUT_FOR_INELIGIBLE_EMPLOYEE", severity="ERROR",
                                     message="Payroll inputs exist for an employee who is not eligible for this run."))
    session.flush()

    run.calc_seconds = round(time.perf_counter() - t0, 3)
    run.calculated_at = utcnow()
    run.totals = {
        "employees_processed": len(employees), "employees_successful": ok, "employees_with_errors": errors,
        "employees_requiring_review": review, **{k: str(money(v)) for k, v in totals.items()},
    }
    audit(session, user, "PAYROLL_RECALCULATED" if recalculation else "PAYROLL_CALCULATED", "payroll_run",
          run.payroll_run_id, None, {"employees": len(employees), "errors": errors, "seconds": run.calc_seconds})

    # validation, anomaly detection and reconciliation run automatically after calculation
    from app.services.anomalies import detect_anomalies
    from app.services.reconciliation import reconcile_run
    from app.services.validation import validate_run

    validate_run(session, run)
    detect_anomalies(session, run)
    reconcile_run(session, run)
    run.status = "VALIDATION_REQUIRED" if blocking_exceptions(session, run) else "READY_FOR_APPROVAL"
    session.flush()
    return run.totals


def blocking_exceptions(session: Session, run: PayrollRun) -> int:
    return len(session.scalars(select(PayrollException.exception_id).where(
        PayrollException.payroll_run_id == run.payroll_run_id, PayrollException.status == "OPEN",
        PayrollException.severity.in_(("ERROR", "CRITICAL")))).all())


def resolve_exception(session: Session, user, exc: PayrollException, note: str, status: str = "RESOLVED") -> None:
    if exc.severity == "CRITICAL" and status == "ACKNOWLEDGED":
        raise WorkflowError("CRITICAL exceptions must be fixed and recalculated, not acknowledged.")
    if not note:
        raise WorkflowError("A resolution note is required.")
    exc.status, exc.resolution_note, exc.resolved_by = status, note, getattr(user, "user_id", None)
    audit(session, user, "EXCEPTION_" + status, "payroll_exception", exc.exception_id, None,
          {"code": exc.code, "severity": exc.severity}, note)
    run = session.get(PayrollRun, exc.payroll_run_id) if exc.payroll_run_id else None
    if run and run.status == "VALIDATION_REQUIRED" and not blocking_exceptions(session, run):
        run.status = "READY_FOR_APPROVAL"


# ------------------------------------------------------------------ approval & lifecycle


def approve_run(session: Session, user, run: PayrollRun) -> None:
    if run.status != "READY_FOR_APPROVAL":
        raise WorkflowError(f"Run is {run.status}; only READY_FOR_APPROVAL runs can be approved.")
    crit = session.scalars(select(PayrollException).where(
        PayrollException.payroll_run_id == run.payroll_run_id, PayrollException.severity == "CRITICAL",
        PayrollException.status != "RESOLVED")).first()
    if crit or blocking_exceptions(session, run):
        raise WorkflowError("Payroll cannot be approved while critical/error exceptions are open.")
    uid = getattr(user, "user_id", None)
    if get_settings().env == "production" and uid is not None and uid == run.created_by:
        raise WorkflowError("Four-eyes control: the approver must be different from the preparer.")
    run.status, run.approved_by, run.approved_at, run.locked_at = "APPROVED", uid, utcnow(), utcnow()
    audit(session, user, "PAYROLL_APPROVED", "payroll_run", run.payroll_run_id, None, run.totals)


def mark_submitted(session: Session, user, run: PayrollRun) -> None:
    if run.status != "APPROVED":
        raise WorkflowError("Only APPROVED runs can move to SUBMITTED.")
    run.status = "SUBMITTED"
    audit(session, user, "PAYROLL_SUBMITTED", "payroll_run", run.payroll_run_id)


def complete_run(session: Session, user, run: PayrollRun) -> None:
    if run.status != "SUBMITTED":
        raise WorkflowError("Only SUBMITTED runs can be completed.")
    run.status = "COMPLETED"
    audit(session, user, "PAYROLL_COMPLETED", "payroll_run", run.payroll_run_id)


def reverse_run(session: Session, user, run: PayrollRun, reason: str) -> PayrollRun:
    if run.status not in FINAL_STATUSES:
        raise WorkflowError("Only approved/submitted/completed runs can be reversed.")
    if not reason:
        raise WorkflowError("A reason is required to reverse a payroll run.")
    before = run.status
    run.status = "REVERSED"
    audit(session, user, "PAYROLL_REVERSED", "payroll_run", run.payroll_run_id, {"status": before},
          {"status": "REVERSED"}, reason)
    correction = create_run(session, user, run.company_id, run.tax_year, run.frequency, run.payroll_period,
                            run.period_start, run.period_end, run.payment_date, "CORRECTION", run.payroll_run_id)
    # carry the original inputs forward so the administrator corrects them rather than re-keying everything
    for rec in session.scalars(select(PayrollInputRecord).where(PayrollInputRecord.payroll_run_id == run.payroll_run_id)
                               .options(selectinload(PayrollInputRecord.earnings), selectinload(PayrollInputRecord.deductions))):
        set_inputs(session, user, correction, rec.employee_id,
                   [{"type": e.earning_type, "amount": e.amount, "description": e.description, "hours": e.hours,
                     "rate": e.rate} for e in rec.earnings],
                   [{"code": d.code, "amount": d.amount, "description": d.description} for d in rec.deductions])
    return correction
