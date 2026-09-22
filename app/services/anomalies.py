"""Analytical anomaly checks. These flag things for a human to review - they never change a statutory figure."""

from __future__ import annotations

from decimal import Decimal
from statistics import mean, pstdev

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import PayrollException, PayrollResultRecord, PayrollRun
from app.engine.money import D
from app.services.payroll_service import prior_results

PCT = Decimal("0.20")


def _add(session, run, emp_id, code, severity, message) -> int:
    session.add(PayrollException(payroll_run_id=run.payroll_run_id, employee_id=emp_id, source="ANOMALY",
                                 code=code, severity=severity, message=message))
    return 1


def _earn(r: PayrollResultRecord, kind: str) -> Decimal:
    return sum((D(x["amount"]) for x in (r.earnings_detail or []) if x["type"] == kind), Decimal(0))


def detect_anomalies(session: Session, run: PayrollRun, z_threshold: float = 3.0) -> int:
    results = [r for r in session.scalars(select(PayrollResultRecord).where(
        PayrollResultRecord.payroll_run_id == run.payroll_run_id).options(selectinload(PayrollResultRecord.employee)))
        if r.status == "CALCULATED"]
    priors = prior_results(session, run)
    n = 0
    # --- period-on-period per employee ---------------------------------------
    for r in results:
        p = priors.get(r.employee_id)
        if not p or p.payroll_run_id == run.payroll_run_id:
            continue
        eid = r.employee_id
        if p.net_pay > 0 and r.net_pay < p.net_pay * (1 - PCT):
            n += _add(session, run, eid, "NET_DROP_20", "WARNING", f"Net pay fell >20% (€{p.net_pay} → €{r.net_pay}).")
        if p.gross_pay > 0 and r.gross_pay > p.gross_pay * (1 + PCT):
            n += _add(session, run, eid, "GROSS_UP_20", "WARNING", f"Gross pay rose >20% (€{p.gross_pay} → €{r.gross_pay}).")
        if p.paye > 0 and r.paye == 0 and r.gross_pay > 0:
            n += _add(session, run, eid, "PAYE_ZERO", "WARNING", "PAYE dropped to zero while pay continues.")
        if p.usc > 0 and r.usc == 0 and r.gross_pay > 0:
            n += _add(session, run, eid, "USC_ZERO", "WARNING", "USC dropped to zero while pay continues.")
        if p.prsi_subclass and r.prsi_subclass and p.prsi_class != r.prsi_class:
            n += _add(session, run, eid, "PRSI_CLASS_CHANGED", "WARNING",
                 f"PRSI class changed {p.prsi_class} → {r.prsi_class}.")
        # duplicate earnings: identical non-basic line amounts repeated in the same period
        lines = [(x["type"], x["amount"]) for x in (r.earnings_detail or []) if x["type"] not in ("BASIC", "HOURLY")]
        if len(lines) != len(set(lines)):
            n += _add(session, run, eid, "DUPLICATE_EARNING", "WARNING", "The same earning type and amount appears twice.")

    # --- cross-sectional z-scores (overtime / bonus relative to basic) --------
    for kind, code in (("OVERTIME", "HIGH_OVERTIME"), ("BONUS", "HIGH_BONUS")):
        vals = [(r, _earn(r, kind)) for r in results]
        nonzero = [float(v) for _, v in vals if v > 0]
        if len(nonzero) >= 8:
            mu, sd = mean(nonzero), pstdev(nonzero)
            for r, v in vals:
                if v > 0 and sd > 0 and (float(v) - mu) / sd > z_threshold:
                    n += _add(session, run, r.employee_id, code, "WARNING",
                         f"{kind.title()} €{v} is {((float(v) - mu) / sd):.1f} standard deviations above the run average "
                         f"(€{mu:,.2f}).")

    # --- department cost movement --------------------------------------------
    cur: dict[int | None, Decimal] = {}
    prev: dict[int | None, Decimal] = {}
    for r in results:
        cur[r.employee.department_id] = cur.get(r.employee.department_id, Decimal(0)) + r.employer_cost
        p = priors.get(r.employee_id)
        if p and p.payroll_run_id != run.payroll_run_id:
            prev[r.employee.department_id] = prev.get(r.employee.department_id, Decimal(0)) + p.employer_cost
    for dept, v in cur.items():
        pv = prev.get(dept)
        if pv and abs(v - pv) / pv > Decimal("0.15"):
            n += _add(session, run, None, "DEPT_COST_SHIFT", "INFO",
                 f"Department {dept} employer cost moved {((v - pv) / pv * 100):.1f}% vs previous period.")
    session.flush()
    return n
