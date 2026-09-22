"""Reports: payroll register, liabilities, GL journal, CSV/Excel export."""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import mask_ppsn
from app.db.models import Employee, PayrollResultRecord, PayrollRun
from app.engine.money import D, money

REGISTER_COLS = ["gross_pay", "bik", "pay_for_tax", "paye", "usc", "prsi_ee", "prsi_er", "lpt", "pension_ee",
                 "pension_er", "other_deductions", "net_pay", "employer_cost", "statutory_liability"]


def register(session: Session, run: PayrollRun, include_errors: bool = True) -> pd.DataFrame:
    rows = session.scalars(select(PayrollResultRecord).where(PayrollResultRecord.payroll_run_id == run.payroll_run_id)
                           .options(selectinload(PayrollResultRecord.employee).selectinload(Employee.department))).all()
    data = []
    for r in rows:
        if r.status != "CALCULATED" and not include_errors:
            continue
        e = r.employee
        d: dict[str, Any] = {"result_id": r.result_id, "employee_id": e.employee_id, "employee_number": e.employee_number,
                             "name": e.full_name, "ppsn": mask_ppsn(e.ppsn),
                             "department": e.department.name if e.department else None, "status": r.status,
                             "tax_basis": r.tax_basis_applied, "usc_status": r.usc_status_applied,
                             "prsi_subclass": r.prsi_subclass, "error": r.error_message}
        for c in REGISTER_COLS:
            d[c] = float(getattr(r, c))
        for kind in ("OVERTIME", "BONUS", "COMMISSION"):
            d[kind.lower()] = float(sum((D(x["amount"]) for x in (r.earnings_detail or []) if x["type"] == kind), Decimal(0)))
        data.append(d)
    return pd.DataFrame(data)


def liabilities(run: PayrollRun) -> list[dict[str, Any]]:
    t = run.totals or {}
    items = [("PAYE", "paye"), ("USC", "usc"), ("Employee PRSI", "prsi_ee"), ("Employer PRSI", "prsi_er"), ("LPT", "lpt")]
    out = [{"liability": label, "amount": D(t.get(k, "0"))} for label, k in items]
    out.append({"liability": "Total due to Revenue", "amount": sum((x["amount"] for x in out), Decimal(0))})
    return out


def journal(run: PayrollRun) -> list[dict[str, Any]]:
    t = {k: D(v) for k, v in (run.totals or {}).items() if k not in (
        "employees_processed", "employees_successful", "employees_with_errors", "employees_requiring_review")}
    g = lambda k: t.get(k, Decimal(0))  # noqa: E731
    lines = [
        ("6000", "Gross wages expense", g("gross_pay"), Decimal(0)),
        ("6010", "Employer PRSI expense", g("prsi_er"), Decimal(0)),
        ("6020", "Employer pension expense", g("pension_er"), Decimal(0)),
        ("2200", "PAYE payable", Decimal(0), g("paye")),
        ("2201", "USC payable", Decimal(0), g("usc")),
        ("2202", "Employee PRSI payable", Decimal(0), g("prsi_ee")),
        ("2203", "Employer PRSI payable", Decimal(0), g("prsi_er")),
        ("2204", "LPT payable", Decimal(0), g("lpt")),
        ("2210", "Pension payable", Decimal(0), g("pension_ee") + g("pension_er")),
        ("2220", "Other deductions payable", Decimal(0), g("other_deductions")),
        ("2300", "Net wages payable", Decimal(0), g("net_pay")),
    ]
    out = [{"account": a, "description": d, "debit": money(dr), "credit": money(cr),
            "reference": f"PAYROLL-{run.tax_year}-{run.frequency[0]}{run.payroll_period:02d}",
            "date": run.payment_date.isoformat()} for a, d, dr, cr in lines]
    return out


def journal_balanced(lines: list[dict[str, Any]]) -> bool:
    return sum(x["debit"] for x in lines) == sum(x["credit"] for x in lines)


def to_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def to_excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
    return buf.getvalue()


def run_workbook(session: Session, run: PayrollRun) -> bytes:
    reg = register(session, run)
    liab = pd.DataFrame([{**x, "amount": float(x["amount"])} for x in liabilities(run)])
    jr = pd.DataFrame([{**x, "debit": float(x["debit"]), "credit": float(x["credit"])} for x in journal(run)])
    summary = pd.DataFrame([{"metric": k, "value": v} for k, v in (run.totals or {}).items()])
    return to_excel({"Summary": summary, "Register": reg, "Liabilities": liab, "Journal": jr})


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """JSON-safe records (NaN → null, dates → ISO)."""
    import json

    return json.loads(df.to_json(orient="records", date_format="iso")) if not df.empty else []
