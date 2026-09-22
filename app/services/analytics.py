"""Payroll analytics (pandas). Read-only views over finalised/calculated results."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Department, Employee, PayrollException, PayrollResultRecord, PayrollRun

LIVE_STATUSES = ("READY_FOR_APPROVAL", "VALIDATION_REQUIRED", "APPROVED", "SUBMITTED", "COMPLETED")
NUM = ["gross_pay", "bik", "paye", "usc", "prsi_ee", "prsi_er", "lpt", "pension_ee", "pension_er", "net_pay",
       "employer_cost", "statutory_liability"]


def results_frame(session: Session, company_id: int, tax_year: int | None = None,
                  statuses: tuple[str, ...] = LIVE_STATUSES) -> pd.DataFrame:
    q = (select(PayrollResultRecord, PayrollRun, Employee, Department)
         .join(PayrollRun, PayrollResultRecord.payroll_run_id == PayrollRun.payroll_run_id)
         .join(Employee, PayrollResultRecord.employee_id == Employee.employee_id)
         .outerjoin(Department, Employee.department_id == Department.department_id)
         .where(PayrollRun.company_id == company_id, PayrollRun.status.in_(statuses),
                PayrollResultRecord.status == "CALCULATED"))
    if tax_year:
        q = q.where(PayrollRun.tax_year == tax_year)
    rows = []
    for r, run, e, d in session.execute(q):
        row = {"run_id": run.payroll_run_id, "period": run.payroll_period, "payment_date": run.payment_date,
               "run_status": run.status, "employee_id": e.employee_id, "employee_number": e.employee_number,
               "name": e.full_name, "department": d.name if d else "Unassigned",
               "dept_budget": float(d.monthly_budget) if d and d.monthly_budget else None,
               "annual_salary": float(e.annual_salary or 0)}
        for c in NUM:
            row[c] = float(getattr(r, c))
        for kind in ("BASIC", "HOURLY", "OVERTIME", "BONUS", "COMMISSION", "HOLIDAY_PAY", "ALLOWANCE"):
            row[kind.lower()] = sum(float(x["amount"]) for x in (r.earnings_detail or []) if x["type"] == kind)
        rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["salary_cost"] = df["basic"] + df["hourly"]
        df["period_label"] = df["payment_date"].astype(str).str[:7]
    return df


def trend(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    g = df.groupby(["period", "period_label"], as_index=False)[NUM + ["overtime", "bonus", "salary_cost"]].sum()
    g["headcount"] = df.groupby("period")["employee_id"].nunique().values
    return g.sort_values("period")


def by_department(df: pd.DataFrame, period: int | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    d = df if period is None else df[df["period"] == period]
    g = d.groupby("department").agg(headcount=("employee_id", "nunique"), gross_pay=("gross_pay", "sum"),
                                     net_pay=("net_pay", "sum"), overtime=("overtime", "sum"), bonus=("bonus", "sum"),
                                     prsi_er=("prsi_er", "sum"), pension_er=("pension_er", "sum"),
                                     employer_cost=("employer_cost", "sum"), avg_salary=("annual_salary", "mean"),
                                     budget=("dept_budget", "first")).reset_index()
    return g.sort_values("employer_cost", ascending=False)


def variance(df: pd.DataFrame, period: int) -> pd.DataFrame:
    """Current vs previous period vs budget, by department."""
    cur = by_department(df, period)[["department", "employer_cost", "budget"]].rename(columns={"employer_cost": "current"})
    prev = by_department(df, period - 1)
    prev = prev[["department", "employer_cost"]].rename(columns={"employer_cost": "previous"}) if not prev.empty else \
        pd.DataFrame(columns=["department", "previous"])
    v = cur.merge(prev, on="department", how="left")
    v["vs_previous"] = v["current"] - v["previous"]
    v["vs_previous_pct"] = (v["vs_previous"] / v["previous"] * 100).round(1)
    v["vs_budget"] = v["current"] - v["budget"]
    v["vs_budget_pct"] = (v["vs_budget"] / v["budget"] * 100).round(1)
    return v


def top_overtime(df: pd.DataFrame, period: int, n: int = 10) -> pd.DataFrame:
    d = df[(df["period"] == period) & (df["overtime"] > 0)]
    return d.nlargest(n, "overtime")[["employee_number", "name", "department", "overtime", "gross_pay"]]


def exceptions_frame(session: Session, run_id: int | None = None, company_id: int | None = None) -> pd.DataFrame:
    q = select(PayrollException, Employee).outerjoin(Employee, PayrollException.employee_id == Employee.employee_id)
    if run_id:
        q = q.where(PayrollException.payroll_run_id == run_id)
    if company_id:
        q = q.join(PayrollRun, PayrollException.payroll_run_id == PayrollRun.payroll_run_id).where(
            PayrollRun.company_id == company_id)
    rows = [{"exception_id": x.exception_id, "run_id": x.payroll_run_id, "employee": e.full_name if e else "—",
             "employee_number": e.employee_number if e else None, "source": x.source, "code": x.code,
             "severity": x.severity, "message": x.message, "status": x.status, "resolution_note": x.resolution_note}
            for x, e in session.execute(q)]
    return pd.DataFrame(rows)
