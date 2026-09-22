"""Employee master data, tax profiles and RPN import."""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.base import utcnow
from app.db.models import Employee, EmployeeTaxProfile, RpnRecord
from app.engine.money import D
from app.engine.types import TaxBasis, TaxProfile, UscStatus
from app.services.audit import audit

PPSN_RE = re.compile(r"^(\d{7})([A-W])([A-IW]?)$")
TRACKED = ("annual_salary", "hourly_rate", "department_id", "prsi_class", "pay_frequency", "employment_status",
           "employment_end_date", "pension_scheme", "pension_ee_percent", "pension_er_percent", "job_title", "ppsn")


def ppsn_check_char(digits: str, second: str = "") -> str:
    total = sum(int(d) * w for d, w in zip(digits, range(8, 1, -1)))
    if second and second != "W":
        total += (ord(second) - 64) * 9
    r = total % 23
    return "W" if r == 0 else chr(64 + r)


def validate_ppsn(ppsn: str | None) -> tuple[bool, str]:
    if not ppsn:
        return False, "missing"
    m = PPSN_RE.match(ppsn.strip().upper())
    if not m:
        return False, "format"
    digits, check, second = m.groups()
    return (ppsn_check_char(digits, second) == check, "checksum" if ppsn_check_char(digits, second) != check else "ok")


def create_employee(session: Session, user, data: dict[str, Any]) -> Employee:
    if data.get("ppsn"):
        ok, why = validate_ppsn(data["ppsn"])
        if not ok:
            raise ValueError(f"Invalid PPSN ({why})")
        data["ppsn"] = data["ppsn"].strip().upper()
    emp = Employee(**data)
    session.add(emp)
    session.flush()
    audit(session, user, "EMPLOYEE_CREATED", "employee", emp.employee_id, None,
          {k: data.get(k) for k in ("employee_number", "first_name", "last_name", "ppsn", "annual_salary", "department_id")})
    return emp


def update_employee(session: Session, user, emp: Employee, changes: dict[str, Any], reason: str | None = None) -> Employee:
    before, after = {}, {}
    for k, v in changes.items():
        if k == "ppsn" and v:
            ok, why = validate_ppsn(v)
            if not ok:
                raise ValueError(f"Invalid PPSN ({why})")
            v = v.strip().upper()
        old = getattr(emp, k)
        if old != v:
            before[k], after[k] = old, v
            setattr(emp, k, v)
    if after:
        action = "SALARY_CHANGED" if {"annual_salary", "hourly_rate"} & after.keys() else "EMPLOYEE_UPDATED"
        audit(session, user, action, "employee", emp.employee_id, before, after, reason)
    return emp


def upsert_tax_profile(session: Session, user, emp: Employee, values: dict[str, Any], source: str, reason: str) -> EmployeeTaxProfile:
    prof = emp.tax_profile
    if prof is None:
        prof = EmployeeTaxProfile(employee_id=emp.employee_id)
        session.add(prof)
        emp.tax_profile = prof
        before: dict[str, Any] = {}
    else:
        before = {k: getattr(prof, k) for k in values}
    for k, v in values.items():
        setattr(prof, k, v)
    prof.rpn_source = source
    prof.rpn_imported_at = utcnow()
    audit(session, user, "TAX_PROFILE_CHANGED", "employee_tax_profile", emp.employee_id, before, values, reason)
    return prof


RPN_FIELDS = ("employee_number", "rpn_number", "tax_basis", "annual_tax_credits", "annual_srcop", "usc_status",
              "effective_date")


def import_rpn_csv(session: Session, user, company_id: int, content: str, tax_year: int) -> dict[str, Any]:
    """Import RPN data (CSV extract). Real deployments would pull RPNs from Revenue's API - see REVENUE_INTEGRATION.md."""
    reader = csv.DictReader(io.StringIO(content))
    missing = [f for f in RPN_FIELDS if f not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"RPN file missing columns: {missing}")
    emps = {e.employee_number: e for e in session.scalars(
        select(Employee).where(Employee.company_id == company_id).options(selectinload(Employee.tax_profile)))}
    imported, errors = 0, []
    for i, row in enumerate(reader, start=2):
        emp = emps.get(row["employee_number"].strip())
        if emp is None:
            errors.append({"line": i, "error": f"Unknown employee {row['employee_number']}"})
            continue
        try:
            basis = TaxBasis(row["tax_basis"].strip().upper())
            usc = UscStatus(row["usc_status"].strip().upper())
            vals = dict(
                tax_basis=basis.value, usc_status=usc.value,
                annual_tax_credits=D(row["annual_tax_credits"]), annual_srcop=D(row["annual_srcop"]),
                lpt_annual=D(row.get("lpt_annual") or 0), prior_pay_for_tax=D(row.get("prior_pay_for_tax") or 0),
                prior_tax=D(row.get("prior_tax") or 0), prior_usc_pay=D(row.get("prior_usc_pay") or 0),
                prior_usc=D(row.get("prior_usc") or 0),
            )
            eff = date.fromisoformat(row["effective_date"])
        except Exception as exc:  # noqa: BLE001 - report every bad line, never partially guess
            errors.append({"line": i, "error": f"Invalid value: {exc}"})
            continue
        exists = session.scalar(select(RpnRecord).where(RpnRecord.employee_id == emp.employee_id,
                                                        RpnRecord.rpn_number == row["rpn_number"]))
        if exists:
            errors.append({"line": i, "error": f"RPN {row['rpn_number']} already imported"})
            continue
        session.add(RpnRecord(employee_id=emp.employee_id, tax_year=tax_year, rpn_number=row["rpn_number"],
                              employment_id=emp.employment_id, effective_date=eff, source="CSV_IMPORT",
                              raw=dict(row), **{k: v for k, v in vals.items()}))
        upsert_tax_profile(session, user, emp, {**vals, "rpn_number": row["rpn_number"], "rpn_effective_date": eff},
                           "CSV_IMPORT", f"RPN {row['rpn_number']} imported")
        imported += 1
    audit(session, user, "RPN_IMPORTED", "company", company_id, None, {"imported": imported, "errors": len(errors)})
    return {"imported": imported, "errors": errors}


def to_engine_profile(emp: Employee) -> TaxProfile:
    p = emp.tax_profile
    ppsn_ok = validate_ppsn(emp.ppsn)[0]
    if p is None or p.rpn_number is None:
        return TaxProfile(tax_basis=None, annual_tax_credits=None, annual_srcop=None, usc_status=None,
                          ppsn_present=ppsn_ok, rpn_present=False)
    return TaxProfile(
        tax_basis=TaxBasis(p.tax_basis) if p.tax_basis else None,
        annual_tax_credits=D(p.annual_tax_credits) if p.annual_tax_credits is not None else None,
        annual_srcop=D(p.annual_srcop) if p.annual_srcop is not None else None,
        usc_status=UscStatus(p.usc_status) if p.usc_status else None,
        ppsn_present=ppsn_ok, rpn_present=True, rpn_number=p.rpn_number,
        lpt_annual=D(p.lpt_annual or 0), prior_pay_for_tax=D(p.prior_pay_for_tax or 0), prior_tax=D(p.prior_tax or 0),
        prior_usc_pay=D(p.prior_usc_pay or 0), prior_usc=D(p.prior_usc or 0),
    )


def standard_pay(emp: Employee, frequency: str) -> Decimal:
    ppy = {"WEEKLY": 52, "FORTNIGHTLY": 26, "MONTHLY": 12}[frequency]
    if emp.salary_type == "SALARY":
        return (D(emp.annual_salary or 0) / ppy).quantize(Decimal("0.01"))
    weeks = {"WEEKLY": Decimal(1), "FORTNIGHTLY": Decimal(2), "MONTHLY": Decimal(52) / Decimal(12)}[frequency]
    return (D(emp.hourly_rate or 0) * D(emp.standard_hours or 0) * weeks).quantize(Decimal("0.01"))
