"""Export portfolio examples from the seeded demo database into docs/examples and sample_data/."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.security import mask_ppsn
from app.db.base import session_scope
from app.db.models import Employee, PayrollResultRecord, PayrollRun
from app.services import reports
from app.services.payslips import render_html, render_pdf
from app.services.revenue import prepare_submission

EX = Path("docs/examples")
SD = Path("sample_data")


def main() -> None:
    EX.mkdir(parents=True, exist_ok=True)
    SD.mkdir(exist_ok=True)
    with session_scope() as s:
        emps = s.scalars(select(Employee).options(selectinload(Employee.department), selectinload(Employee.tax_profile))
                         .order_by(Employee.employee_number)).all()
        pd.DataFrame([{
            "employee_number": e.employee_number, "first_name": e.first_name, "last_name": e.last_name,
            "ppsn_masked": mask_ppsn(e.ppsn), "department": e.department.name if e.department else None,
            "job_title": e.job_title, "pay_frequency": e.pay_frequency, "salary_type": e.salary_type,
            "annual_salary": e.annual_salary, "hourly_rate": e.hourly_rate, "standard_hours": e.standard_hours,
            "prsi_class": e.prsi_class, "pension_scheme": e.pension_scheme, "pension_ee_percent": e.pension_ee_percent,
            "pension_er_percent": e.pension_er_percent, "employment_start_date": e.employment_start_date,
            "employment_end_date": e.employment_end_date,
            "tax_basis": e.tax_profile.tax_basis if e.tax_profile else None,
            "annual_tax_credits": e.tax_profile.annual_tax_credits if e.tax_profile else None,
            "annual_srcop": e.tax_profile.annual_srcop if e.tax_profile else None,
            "usc_status": e.tax_profile.usc_status if e.tax_profile else None,
            "lpt_annual": e.tax_profile.lpt_annual if e.tax_profile else None,
            "benefits": ";".join(b.benefit_type for b in e.benefits),
        } for e in emps]).to_csv(SD / "synthetic_employees_300.csv", index=False)

        (SD / "rpn_import_example.csv").write_text(
            "employee_number,rpn_number,tax_basis,annual_tax_credits,annual_srcop,usc_status,lpt_annual,prior_pay_for_tax,"
            "prior_tax,prior_usc_pay,prior_usc,effective_date\n"
            "E0001,RPN2026000012,CUMULATIVE,4000,44000,ORDINARY,315,0,0,0,0,2026-09-01\n"
            "E0002,RPN2026000022,WEEK1_MONTH1,4000,44000,ORDINARY,0,0,0,0,0,2026-09-01\n")
        (SD / "payroll_inputs_example.csv").write_text(
            "employee_number,type,amount,description,hours\n"
            "E0001,OVERTIME,184.62,Overtime 8h @ 1.5,8\n"
            "E0002,BONUS,750,Quarterly bonus,\n"
            "E0003,COMMISSION,420,Sales commission,\n"
            "E0004,DEDUCTION:UNION,18.50,Union subscription,\n")

        # latest completed monthly run = the "example 300-employee payroll run"
        run = s.scalars(select(PayrollRun).where(PayrollRun.frequency == "MONTHLY", PayrollRun.status == "COMPLETED")
                        .order_by(PayrollRun.payroll_period.desc())).first()
        (EX / "payroll_run_P8_2026.xlsx").write_bytes(reports.run_workbook(s, run))
        pd.DataFrame(reports.journal(run)).to_csv(EX / "payroll_journal_P8_2026.csv", index=False)
        (EX / "payroll_run_P8_summary.json").write_text(json.dumps(run.totals, indent=2))
        sub = prepare_submission(s, None, run)
        payload = json.loads(json.dumps(sub.payload))
        for line in payload["payslips"]:
            line["employeeID"]["employeePpsn"] = mask_ppsn(line["employeeID"]["employeePpsn"])
        (EX / "revenue_submission_P8_masked.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))

        # example payslip: an employee with pension, LPT and BIK makes the best demo
        r = None
        for cand in s.scalars(select(PayrollResultRecord).where(PayrollResultRecord.payroll_run_id == run.payroll_run_id,
                                                                PayrollResultRecord.status == "CALCULATED")
                              .options(selectinload(PayrollResultRecord.result_deductions))):
            if cand.bik > 0 and cand.lpt > 0 and cand.pension_ee > 0:
                r = cand
                break
        r = r or cand
        (EX / "example_payslip.html").write_text(render_html(s, r))
        (EX / "example_payslip.pdf").write_bytes(render_pdf(s, r))
        (EX / "example_calculation_trace.json").write_text(json.dumps(
            {"employee_result_id": r.result_id, "rules_used": r.rules_used, "trace": r.trace}, indent=2, ensure_ascii=False))
        print("examples written; payslip for result", r.result_id)


if __name__ == "__main__":
    main()
