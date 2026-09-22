"""Reconciliation: independent re-summation of employee lines vs run totals and liability lines."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import PayrollDeduction, PayrollException, PayrollResultRecord, PayrollRun
from app.engine.money import D

CHECKS = [
    ("gross_pay", "Sum of employee gross = payroll gross total"),
    ("net_pay", "Sum of employee net = payroll net total"),
    ("paye", "Sum of PAYE deductions = PAYE liability"),
    ("usc", "Sum of USC deductions = USC liability"),
    ("prsi_ee", "Sum of employee PRSI = employee PRSI liability"),
    ("prsi_er", "Sum of employer PRSI = employer PRSI liability"),
    ("lpt", "Sum of LPT deductions = LPT liability"),
    ("employer_cost", "Sum of employer cost = total employer cost"),
    ("statutory_liability", "Sum of liabilities = statutory liability"),
]
LINE_CODES = {"paye": "PAYE", "usc": "USC", "prsi_ee": "PRSI_EE", "lpt": "LPT"}


def reconcile_run(session: Session, run: PayrollRun, record: bool = True) -> list[dict[str, Any]]:
    rid = run.payroll_run_id
    ok_filter = (PayrollResultRecord.payroll_run_id == rid, PayrollResultRecord.status == "CALCULATED")
    out = []
    totals = run.totals or {}
    for field, label in CHECKS:
        col_sum = D(session.scalar(select(func.coalesce(func.sum(getattr(PayrollResultRecord, field)), 0)).where(*ok_filter)))
        header = D(totals.get(field, "0"))
        item = {"check": label, "field": field, "employee_sum": str(col_sum), "run_total": str(header),
                "difference": str(col_sum - header), "status": "OK" if abs(col_sum - header) <= Decimal("0.01") else "MISMATCH"}
        # deduction lines are a third, independent representation
        if field in LINE_CODES:
            line_sum = D(session.scalar(
                select(func.coalesce(func.sum(PayrollDeduction.amount), 0)).join(
                    PayrollResultRecord, PayrollDeduction.result_id == PayrollResultRecord.result_id)
                .where(*ok_filter, PayrollDeduction.code == LINE_CODES[field])))
            # refunds are stored as zero lines, so line sum can exceed the (net-of-refund) column sum
            refunds = D(session.scalar(select(func.coalesce(func.sum(getattr(PayrollResultRecord, field)), 0))
                                       .where(*ok_filter, getattr(PayrollResultRecord, field) < 0)))
            item["deduction_line_sum"] = str(line_sum + refunds)
            if abs(line_sum + refunds - col_sum) > Decimal("0.01"):
                item["status"] = "MISMATCH"
        out.append(item)
        if record and item["status"] == "MISMATCH":
            session.add(PayrollException(payroll_run_id=rid, source="RECONCILIATION", code=f"RECON_{field.upper()}",
                                         severity="CRITICAL", message=f"{label}: difference €{item['difference']}"))
    session.flush()
    return out
