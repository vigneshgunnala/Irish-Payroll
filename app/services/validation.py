"""Pre-approval validation rules (INFO / WARNING / ERROR / CRITICAL)."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Employee, PayrollException, PayrollResultRecord, PayrollRun
from app.engine.money import ZERO, D
from app.services.employees import validate_ppsn
from app.services.payroll_service import prior_results

HIGH_SALARY = Decimal("250000")
VALID_PRSI = {"A", "B", "C", "D", "H", "J", "K", "M", "S"}


def _add(session, run, emp_id, code, severity, message):
    session.add(PayrollException(payroll_run_id=run.payroll_run_id, employee_id=emp_id, source="VALIDATION",
                                 code=code, severity=severity, message=message))


def validate_run(session: Session, run: PayrollRun) -> int:
    results = list(session.scalars(select(PayrollResultRecord).where(
        PayrollResultRecord.payroll_run_id == run.payroll_run_id)
        .options(selectinload(PayrollResultRecord.employee).selectinload(Employee.tax_profile))))
    priors = prior_results(session, run)
    before = len(session.new)
    counts = Counter(r.employee_id for r in results)
    ppsn_counts = Counter(r.employee.ppsn for r in results if r.employee.ppsn)

    for r in results:
        e = r.employee
        eid = e.employee_id
        if counts[eid] > 1:
            _add(session, run, eid, "DUPLICATE_PAYROLL_RECORD", "CRITICAL", "Employee appears more than once in this run.")
        if e.ppsn and ppsn_counts[e.ppsn] > 1:
            _add(session, run, eid, "DUPLICATE_EMPLOYEE", "ERROR",
                 "Same PPSN held by more than one employee record in this run (possible duplicate employee).")
        ok, why = validate_ppsn(e.ppsn)
        if not e.ppsn:
            _add(session, run, eid, "PPSN_MISSING", "WARNING", "No PPSN held - emergency tax at the higher rate applies.")
        elif not ok:
            _add(session, run, eid, "PPSN_INVALID", "ERROR", f"PPSN fails the {why} check.")
        if e.tax_profile is None or not e.tax_profile.rpn_number:
            _add(session, run, eid, "RPN_MISSING", "WARNING",
                 "No RPN held for this employment - emergency basis applied. Request an RPN from Revenue.")
        if not e.prsi_class or e.prsi_class[:1].upper() not in VALID_PRSI:
            _add(session, run, eid, "PRSI_CLASS_INVALID", "CRITICAL", f"PRSI class '{e.prsi_class}' is missing/invalid.")
        if e.department_id is None:
            _add(session, run, eid, "DEPARTMENT_MISSING", "INFO", "No department - payroll cost cannot be allocated.")
        if e.annual_salary and D(e.annual_salary) > HIGH_SALARY:
            _add(session, run, eid, "HIGH_SALARY", "WARNING", f"Annual salary €{e.annual_salary:,} is unusually high.")
        if e.tax_profile and e.tax_profile.usc_status == "REDUCED" and e.annual_salary and D(e.annual_salary) > 60000:
            _add(session, run, eid, "USC_REDUCED_INCOME", "WARNING",
                 "Reduced USC status but salary exceeds €60,000 - confirm the RPN.")

        if r.status != "CALCULATED":
            continue  # engine already raised a CRITICAL exception
        if r.gross_pay < 0:
            _add(session, run, eid, "NEGATIVE_GROSS", "CRITICAL", "Gross pay is negative.")
        if r.net_pay < 0:
            _add(session, run, eid, "NEGATIVE_NET", "ERROR", f"Net pay is negative (€{r.net_pay}).")
        if r.gross_pay == 0:
            _add(session, run, eid, "ZERO_PAY", "INFO", "Zero pay this period.")
        if r.pay_for_tax > 0 and r.paye > r.pay_for_tax * Decimal("0.40") + Decimal("0.05"):
            _add(session, run, eid, "PAYE_UNUSUAL", "ERROR", "PAYE exceeds 40% of pay for tax this period.")
        if r.pay_for_usc > 0 and r.usc > r.pay_for_usc * Decimal("0.08") + Decimal("0.05"):
            _add(session, run, eid, "USC_UNUSUAL", "ERROR", "USC exceeds 8% of USC pay this period.")
        if r.prsi_class == "A" and r.pay_for_prsi > 0 and r.prsi_er == 0:
            _add(session, run, eid, "PRSI_UNEXPECTED", "ERROR", "Class A pay with no employer PRSI.")

        # internal arithmetic re-check (independent of the engine)
        net_check = r.gross_pay - r.paye - r.usc - r.prsi_ee - r.lpt - r.pension_ee - r.other_deductions
        if abs(net_check - r.net_pay) > Decimal("0.01"):
            _add(session, run, eid, "TAX_CALC_MISMATCH", "CRITICAL", "Net pay does not equal gross less deductions.")
        liab = r.paye + r.usc + r.prsi_ee + r.prsi_er + r.lpt
        if abs(liab - r.statutory_liability) > Decimal("0.01"):
            _add(session, run, eid, "LIABILITY_MISMATCH", "CRITICAL", "Employer liability does not reconcile.")
        # YTD continuity
        prior = priors.get(eid)
        if r.ytd:
            prev_tax = D(prior.ytd.get("tax")) if prior and prior.ytd else ZERO
            if abs(D(r.ytd["tax"]) - (prev_tax + r.paye)) > Decimal("0.01"):
                _add(session, run, eid, "YTD_MISMATCH", "CRITICAL", "YTD tax ≠ previous YTD + this period.")
        # salary change vs previous period
        if prior and prior.gross_pay and r.gross_pay:
            base_prev = sum(D(x["amount"]) for x in (prior.earnings_detail or []) if x["type"] in ("BASIC", "HOURLY"))
            base_now = sum(D(x["amount"]) for x in (r.earnings_detail or []) if x["type"] in ("BASIC", "HOURLY"))
            if base_prev and abs(base_now - base_prev) > Decimal("0.01"):
                _add(session, run, eid, "SALARY_CHANGE", "INFO", f"Basic pay changed from €{base_prev} to €{base_now}.")
    session.flush()
    return len(session.new) - before if len(session.new) >= before else 0
