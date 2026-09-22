"""Synthetic demo data. ALL people, companies and identifiers are fictitious and randomly generated."""

from __future__ import annotations

import random
import secrets
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import ROLE_PERMISSIONS, Role, hash_password
from app.db.models import (
    Company,
    Department,
    Employee,
    EmployeeBenefit,
    PayrollRun,
    RoleRecord,
    User,
)
from app.services import payroll_service as ps
from app.services.employees import import_rpn_csv, ppsn_check_char

FIRST = ["Aoife", "Ciara", "Niamh", "Saoirse", "Siobhán", "Orla", "Róisín", "Emma", "Sarah", "Grace", "Chloe", "Aisling",
         "Clodagh", "Méabh", "Sinéad", "Katie", "Laura", "Priya", "Ana", "Zofia", "Conor", "Seán", "Cian", "Darragh",
         "Oisín", "Eoin", "Fionn", "Liam", "Jack", "Adam", "Patrick", "Ciarán", "Pádraig", "Tadhg", "Rory", "Mark",
         "David", "Tomasz", "Rahul", "Lucas", "Mateus", "Diarmuid", "Ronan", "Shane", "Declan", "Brian", "Aoibhinn", "Éabha"]
LAST = ["Murphy", "Kelly", "O'Sullivan", "Walsh", "Smith", "O'Brien", "Byrne", "Ryan", "O'Connor", "O'Neill", "O'Reilly",
        "Doyle", "McCarthy", "Gallagher", "O'Doherty", "Kennedy", "Lynch", "Murray", "Quinn", "Moore", "McLoughlin",
        "Carroll", "Connolly", "Daly", "Connell", "Wilson", "Dunne", "Brennan", "Burke", "Collins", "Campbell", "Clarke",
        "Johnston", "Hughes", "Farrell", "Fitzgerald", "Brown", "Martin", "Maguire", "Nolan", "Flynn", "Kowalski",
        "Nowak", "Sharma", "Silva", "Horgan", "Keane", "Nagle"]
DEPTS = {  # name: (headcount share, salary range, freq, cost centre)
    "Finance": (0.08, (38000, 95000), "MONTHLY", "CC100"),
    "HR": (0.05, (34000, 80000), "MONTHLY", "CC110"),
    "IT": (0.14, (42000, 120000), "MONTHLY", "CC120"),
    "Operations": (0.20, (29000, 60000), "MONTHLY", "CC130"),
    "Sales": (0.13, (32000, 85000), "MONTHLY", "CC140"),
    "Marketing": (0.07, (35000, 82000), "MONTHLY", "CC150"),
    "Customer Service": (0.20, None, "WEEKLY", "CC160"),
    "Administration": (0.08, (28000, 48000), "MONTHLY", "CC170"),
    "Management": (0.05, (90000, 185000), "MONTHLY", "CC180"),
}
TITLES = {"Finance": ["Accountant", "Accounts Payable Clerk", "Financial Analyst"], "HR": ["HR Generalist", "Recruiter"],
          "IT": ["Software Engineer", "Data Analyst", "Support Engineer", "DevOps Engineer"],
          "Operations": ["Operations Associate", "Logistics Coordinator", "Team Lead"],
          "Sales": ["Account Executive", "Sales Representative"], "Marketing": ["Marketing Executive", "Content Specialist"],
          "Customer Service": ["Customer Service Agent", "Senior Agent"], "Administration": ["Administrator", "Receptionist"],
          "Management": ["Head of Department", "Director"]}


def _ppsn(rng: random.Random, used: set[str]) -> str:
    while True:
        digits = "".join(str(rng.randint(0, 9)) for _ in range(7))
        second = rng.choice(["", "A"])
        p = digits + ppsn_check_char(digits, second) + second
        if p not in used:
            used.add(p)
            return p


def _payday_monthly(year: int, month: int) -> date:
    d = date(year, month, 25)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
    return start, end


def ensure_roles_and_users(session: Session, password: str | None = None) -> dict[str, str]:
    """Create roles + one demo user per role. Password comes from the caller/env - never hard-coded."""
    for role in Role:
        if not session.scalar(select(RoleRecord).where(RoleRecord.code == role.value)):
            session.add(RoleRecord(code=role.value, description=role.value.replace("_", " ").title(),
                                   permissions=sorted(p.value for p in ROLE_PERMISSIONS[role])))
    session.flush()
    password = password or secrets.token_urlsafe(12)
    creds = {}
    for role, email, name in [
        (Role.PAYROLL_ADMIN, "payroll.admin@demo.ie", "Pat Admin"),
        (Role.PAYROLL_ANALYST, "payroll.analyst@demo.ie", "Ana Lyst"),
        (Role.HR_ADMIN, "hr.admin@demo.ie", "Hilary Resources"),
        (Role.FINANCE_MANAGER, "finance.manager@demo.ie", "Fin Manager"),
        (Role.SYSTEM_ADMIN, "sys.admin@demo.ie", "Sys Admin"),
    ]:
        if not session.scalar(select(User).where(User.email == email)):
            session.add(User(email=email, full_name=name, password_hash=hash_password(password), role=role.value))
            creds[email] = password
    session.flush()
    return creds


def seed_company(session: Session, n_employees: int = 300, seed: int = 42, tax_year: int = 2026) -> Company:
    rng = random.Random(seed)
    co = Company(legal_name="Corrib Digital Services Limited (fictitious)", trading_name="Corrib Digital",
                 tax_registration_number="9999999TH", employer_registration_details="Synthetic employer - demo only",
                 address="Unit 4, Fictional Business Park, Galway", contact_email="payroll@corrib-digital.example",
                 phone="+353 91 000 0000", payroll_frequency="MONTHLY", financial_year=tax_year)
    session.add(co)
    session.flush()
    depts = {}
    for name, (_share, _, _, cc) in DEPTS.items():
        d = Department(company_id=co.company_id, name=name, cost_centre=cc)
        session.add(d)
        depts[name] = d
    session.flush()

    used: set[str] = set()
    names = list(DEPTS)
    weights = [DEPTS[n][0] for n in names]
    rpn_lines = ["employee_number,rpn_number,tax_basis,annual_tax_credits,annual_srcop,usc_status,lpt_annual,"
                 "prior_pay_for_tax,prior_tax,prior_usc_pay,prior_usc,effective_date"]
    for i in range(1, n_employees + 1):
        dept = rng.choices(names, weights)[0]
        _, sal_range, freq, _ = DEPTS[dept]
        age = rng.randint(19, 66)
        dob = date(tax_year - age, rng.randint(1, 12), rng.randint(1, 28))
        start = date(rng.randint(2012, 2025), rng.randint(1, 12), rng.randint(1, 28))
        end = None
        r = rng.random()
        if r < 0.03:  # joined mid-year
            start = date(tax_year, rng.randint(2, 8), rng.randint(1, 28))
        elif r < 0.05:  # left mid-year
            end = date(tax_year, rng.randint(3, 8), rng.randint(1, 28))
        emp_no = f"E{i:04d}"
        ppsn = _ppsn(rng, used) if rng.random() > 0.01 else None
        data: dict[str, Any] = dict(
            company_id=co.company_id, employee_number=emp_no, first_name=rng.choice(FIRST), last_name=rng.choice(LAST),
            ppsn=ppsn, date_of_birth=dob, employment_start_date=start, employment_end_date=end,
            employment_status="LEFT" if end else "ACTIVE", department_id=depts[dept].department_id,
            job_title=rng.choice(TITLES[dept]), location=rng.choice(["Galway", "Dublin", "Limerick", "Cork", "Remote"]),
            contract_type=rng.choice(["Permanent"] * 8 + ["Fixed-term", "Part-time"]), pay_frequency=freq,
            prsi_class="A", employment_id=str(i), bank_iban_masked="IE•• •••• " + f"{rng.randint(0, 9999):04d}",
        )
        if freq == "WEEKLY":
            data.update(salary_type="HOURLY", hourly_rate=Decimal(str(round(rng.uniform(14.15, 19.5), 2))),
                        standard_hours=Decimal(rng.choice([39, 39, 39, 30, 20])))
        else:
            lo, hi = sal_range  # type: ignore[misc]
            data.update(salary_type="SALARY", annual_salary=Decimal(round(rng.triangular(lo, hi, lo + (hi - lo) * 0.35), -2)))
        if rng.random() < 0.62:
            data.update(pension_scheme=rng.choice(["OCCUPATIONAL"] * 4 + ["PRSA"]),
                        pension_ee_percent=Decimal(rng.choice(["0.03", "0.05", "0.05", "0.06", "0.08"])),
                        pension_er_percent=Decimal(rng.choice(["0.03", "0.05", "0.06"])))
        if dept == "Management" and rng.random() < 0.3:
            data["prsi_class"] = "S"  # proprietary director (Class S via PAYE)
        if age >= 66:
            data["prsi_class"] = "J"  # over pension age
        emp = Employee(**data)
        session.add(emp)
        session.flush()

        # benefits
        if dept in ("Management", "Sales") and rng.random() < 0.35:
            session.add(EmployeeBenefit(employee_id=emp.employee_id, benefit_type="COMPANY_CAR",
                                        description=rng.choice(["Hybrid SUV", "Electric hatchback", "Diesel saloon"]),
                                        omv=Decimal(rng.choice([32000, 38500, 45000, 52000, 61000])),
                                        co2_g_km=Decimal(rng.choice([0, 0, 45, 110, 135, 150])),
                                        business_km=rng.choice([12000, 22000, 30000, 41000, 52000]),
                                        employee_contribution_annual=Decimal(rng.choice([0, 0, 1200]))))
        if rng.random() < 0.15:
            session.add(EmployeeBenefit(employee_id=emp.employee_id, benefit_type="MEDICAL_INSURANCE",
                                        description="Group health insurance", annual_value=Decimal(rng.choice([1450, 1780, 2240]))))

        # RPN (most employees) - figures as Revenue would supply them
        if rng.random() < 0.97 and ppsn:
            kind = rng.random()
            if kind < 0.70:
                credits, srcop = 4000, 44000  # single: personal + employee credit
            elif kind < 0.85:
                credits, srcop = 6000, 53000  # married, one income
            elif kind < 0.95:
                credits, srcop = rng.choice([(4000, 44000), (4000, 35000), (5000, 44000)])
            else:
                credits, srcop = 4000, 44000
            basis = "WEEK1_MONTH1" if rng.random() < 0.04 else "CUMULATIVE"
            usc = "ORDINARY"
            if data.get("standard_hours") == 20 and rng.random() < 0.5:
                usc = "EXEMPT"
            elif age >= 66 and rng.random() < 0.5 and Decimal(data.get("annual_salary") or 0) <= 60000:
                usc = "REDUCED"
            lpt = rng.choice([0, 0, 0, 90, 225, 315, 405, 495, 585, 675, 1035]) if age > 26 else 0
            prior_pay = prior_tax = prior_usc_pay = prior_usc = 0
            if start.year == tax_year and rng.random() < 0.6:  # joiner with pay from a previous employer
                months = start.month - 1
                prior_pay = round(rng.uniform(2200, 3800) * months, 2)
                prior_tax = round(prior_pay * 0.12, 2)
                prior_usc_pay, prior_usc = prior_pay, round(prior_pay * 0.02, 2)
            rpn_lines.append(f"{emp_no},RPN{tax_year}{i:05d}1,{basis},{credits},{srcop},{usc},{lpt},{prior_pay},{prior_tax},"
                             f"{prior_usc_pay},{prior_usc},{tax_year}-01-01")
    session.flush()
    import_rpn_csv(session, None, co.company_id, "\n".join(rpn_lines), tax_year)

    # department monthly budgets = current salary cost × 1.15 (on-cost) - gives the variance view something to compare
    for d in depts.values():
        emps = session.scalars(select(Employee).where(Employee.department_id == d.department_id)).all()
        monthly = sum((Decimal(e.annual_salary or 0) / 12 if e.salary_type == "SALARY" else
                       Decimal(e.hourly_rate or 0) * Decimal(e.standard_hours or 0) * Decimal(52) / 12) for e in emps)
        d.monthly_budget = (monthly * Decimal("1.16")).quantize(Decimal("1"))
    session.flush()
    return co


def variable_inputs(session: Session, run: PayrollRun, rng: random.Random, inject_anomalies: bool = False) -> None:
    emps = ps.eligible_employees(session, run)
    for e in emps:
        dept = e.department.name if e.department else ""
        earnings, deductions = [], []
        if dept in ("Operations", "Customer Service", "IT") and rng.random() < 0.35:
            hrs = Decimal(rng.choice([2, 4, 6, 8, 10, 12]))
            rate = Decimal(e.hourly_rate) if e.hourly_rate else (Decimal(e.annual_salary or 0) / Decimal(1950))
            earnings.append({"type": "OVERTIME", "amount": (hrs * rate * Decimal("1.5")).quantize(Decimal("0.01")),
                             "description": f"Overtime {hrs}h @ 1.5", "hours": hrs})
        if dept == "Sales" and run.frequency == "MONTHLY":
            earnings.append({"type": "COMMISSION", "amount": Decimal(rng.randint(0, 18) * 50), "description": "Sales commission"})
        if run.frequency == "MONTHLY" and run.payroll_period == 3 and rng.random() < 0.5:
            earnings.append({"type": "BONUS", "amount": Decimal(rng.choice([500, 750, 1000, 1500, 2500])),
                             "description": "Annual performance bonus"})
        if dept == "Customer Service" and rng.random() < 0.2:
            earnings.append({"type": "SHIFT_PREMIUM", "amount": Decimal(rng.choice([25, 40, 60])), "description": "Weekend shift"})
        if rng.random() < 0.05:
            deductions.append({"code": "UNION", "amount": Decimal("18.50"), "description": "Union subscription"})
        if earnings or deductions:
            ps.set_inputs(session, None, run, e.employee_id, earnings, deductions)
    if inject_anomalies and emps:
        # deliberate issues so the exceptions queue has something to show
        target = emps[5]
        ps.set_inputs(session, None, run, target.employee_id, [
            {"type": "OVERTIME", "amount": Decimal("4850.00"), "description": "Overtime 120h (check)"},
            {"type": "ALLOWANCE", "amount": Decimal("150.00"), "description": "Travel allowance"},
            {"type": "ALLOWANCE", "amount": Decimal("150.00"), "description": "Travel allowance"}])
        emps[11].prsi_class = None  # data error → CRITICAL, blocks approval until fixed


def process_year(session: Session, company: Company, user, tax_year: int = 2026, finalise_months: int = 8,
                 finalise_weeks: int = 38, current_month: int = 9, current_week: int = 39, seed: int = 7) -> dict[str, Any]:
    rng = random.Random(seed)
    out: dict[str, Any] = {"monthly": [], "weekly": []}
    for m in range(1, current_month + 1):
        s, e = _month_bounds(tax_year, m)
        run = ps.create_run(session, user, company.company_id, tax_year, "MONTHLY", m, s, e, _payday_monthly(tax_year, m))
        variable_inputs(session, run, rng, inject_anomalies=(m == current_month))
        ps.calculate_run(session, user, run)
        if m <= finalise_months:
            _force_finalise(session, user, run)
        out["monthly"].append((run.payroll_run_id, run.status))
    first_friday = date(tax_year, 1, 2)
    for w in range(1, current_week + 1):
        pay = first_friday + timedelta(weeks=w - 1)
        s = date(tax_year, 1, 1) + timedelta(weeks=w - 1)
        run = ps.create_run(session, user, company.company_id, tax_year, "WEEKLY", w, s, s + timedelta(days=6), pay)
        variable_inputs(session, run, rng)
        ps.calculate_run(session, user, run)
        if w <= finalise_weeks:
            _force_finalise(session, user, run)
        out["weekly"].append((run.payroll_run_id, run.status))
    return out


def _force_finalise(session: Session, user, run: PayrollRun) -> None:
    """History months: acknowledge non-critical review items (as an administrator would) then approve & complete."""
    from app.db.models import PayrollException

    for x in session.scalars(select(PayrollException).where(PayrollException.payroll_run_id == run.payroll_run_id,
                                                            PayrollException.status == "OPEN")):
        if x.severity in ("ERROR", "CRITICAL"):
            continue
        x.status, x.resolution_note = "ACKNOWLEDGED", "Reviewed during historical processing (seed)."
    if run.status == "VALIDATION_REQUIRED" and ps.blocking_exceptions(session, run):
        return  # leave it for a human
    run.status = "READY_FOR_APPROVAL"
    ps.approve_run(session, user, run)
    ps.mark_submitted(session, user, run)
    ps.complete_run(session, user, run)
