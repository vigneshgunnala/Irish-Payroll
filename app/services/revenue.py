"""Revenue payroll submission PREPARATION.

This module builds and validates the per-employee pay details Revenue requires in a payroll
submission (gross pay, pay for income tax / USC / PRSI, tax, USC, PRSI class & insurable weeks,
employee & employer PRSI, LPT, RPN reference, pay date, employment identifier).

It does NOT transmit anything to Revenue. Direct submission requires ROS digital certificates,
Revenue's published PAYE Modernisation REST API and message signing - see REVENUE_INTEGRATION.md.
The `RevenueGateway` interface is the seam where a certified integration would plug in.
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Company, Employee, PayrollResultRecord, PayrollRun, RevenueSubmission
from app.services.audit import audit
from app.services.employees import validate_ppsn

SCHEMA_NOTE = ("Field names follow Revenue's published list of employee pay details for payroll submissions; "
               "they have NOT been validated against Revenue's official API schema.")


def _employee_line(e: Employee, r: PayrollResultRecord) -> dict[str, Any]:
    return {
        "employeeID": {"employeePpsn": e.ppsn, "employmentID": e.employment_id},
        "name": {"firstName": e.first_name, "familyName": e.last_name},
        "rpnNumber": e.tax_profile.rpn_number if e.tax_profile else None,
        "taxBasis": r.tax_basis_applied,
        "grossPay": str(r.gross_pay),
        "payForIncomeTax": str(r.pay_for_tax),
        "incomeTaxPaid": str(r.paye),
        "payForEmployeePRSI": str(r.pay_for_prsi),
        "payForEmployerPRSI": str(r.pay_for_prsi),
        "prsiClassDetails": [{"prsiClass": r.prsi_subclass, "insurableWeeks": r.insurable_weeks}],
        "employeePRSIPaid": str(r.prsi_ee),
        "employerPRSIPaid": str(r.prsi_er),
        "payForUSC": str(r.pay_for_usc),
        "uscStatus": r.usc_status_applied,
        "uscPaid": str(r.usc),
        "lptDeducted": str(r.lpt),
        "taxableBenefits": str(r.bik),
        "employeePensionContribution": str(r.pension_ee),
    }


def validate_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    errs = []
    if not payload["header"].get("employerRegistrationNumber"):
        errs.append({"field": "employerRegistrationNumber", "error": "missing"})
    for i, line in enumerate(payload["payslips"]):
        ppsn = line["employeeID"]["employeePpsn"]
        if ppsn and not validate_ppsn(ppsn)[0]:
            errs.append({"line": i, "field": "employeePpsn", "error": "invalid PPSN"})
        if not ppsn:
            errs.append({"line": i, "field": "employeePpsn", "error": "missing - permitted only with emergency basis",
                         "severity": "WARNING"})
        if not line["employeeID"]["employmentID"]:
            errs.append({"line": i, "field": "employmentID", "error": "missing"})
        if line["taxBasis"] != "EMERGENCY" and not line["rpnNumber"]:
            errs.append({"line": i, "field": "rpnNumber", "error": "RPN required for non-emergency basis"})
    return errs


def prepare_submission(session: Session, user, run: PayrollRun) -> RevenueSubmission:
    if run.status not in ("APPROVED", "SUBMITTED", "COMPLETED"):
        raise ValueError("Submission data can only be prepared from an approved payroll run.")
    company = session.get(Company, run.company_id)
    results = session.scalars(select(PayrollResultRecord).where(
        PayrollResultRecord.payroll_run_id == run.payroll_run_id, PayrollResultRecord.status == "CALCULATED")
        .options(selectinload(PayrollResultRecord.employee).selectinload(Employee.tax_profile))).all()
    ref = f"PSR-{run.tax_year}-{run.payroll_run_id}-{uuid.uuid4().hex[:8].upper()}"
    payload = {
        "schemaNote": SCHEMA_NOTE,
        "header": {"employerRegistrationNumber": company.tax_registration_number, "taxYear": run.tax_year,
                   "payDate": run.payment_date.isoformat(), "submissionID": ref, "runReference": run.payroll_run_id,
                   "payFrequency": run.frequency, "lineItemCount": len(results)},
        "payslips": [_employee_line(r.employee, r) for r in results],
    }
    errs = validate_payload(payload)
    blocking = [e for e in errs if e.get("severity", "ERROR") == "ERROR"]
    sub = RevenueSubmission(payroll_run_id=run.payroll_run_id, submission_ref=ref,
                            status="VALIDATION_FAILED" if blocking else "PREPARED", payload=payload,
                            validation_errors=errs, prepared_by=getattr(user, "user_id", None))
    session.add(sub)
    session.flush()
    audit(session, user, "SUBMISSION_PREPARED", "revenue_submission", sub.submission_id, None,
          {"ref": ref, "lines": len(results), "errors": len(errs), "status": sub.status})
    return sub


def export_json(sub: RevenueSubmission) -> bytes:
    return json.dumps(sub.payload, indent=2).encode()


class RevenueGateway(ABC):
    """Integration seam for a future, certified Revenue API client."""

    @abstractmethod
    def submit(self, submission: RevenueSubmission) -> dict[str, Any]: ...

    @abstractmethod
    def fetch_rpns(self, employer_reg: str, tax_year: int) -> list[dict[str, Any]]: ...


class NotConfiguredGateway(RevenueGateway):
    def submit(self, submission: RevenueSubmission) -> dict[str, Any]:
        raise NotImplementedError("Direct Revenue submission is not implemented - export the prepared file instead.")

    def fetch_rpns(self, employer_reg: str, tax_year: int) -> list[dict[str, Any]]:
        raise NotImplementedError("RPN retrieval from Revenue is not implemented - import an RPN CSV instead.")
