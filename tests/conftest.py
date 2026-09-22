from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest

os.environ.setdefault("PAYROLL_SECRET_KEY", "test-secret-key-not-for-production-use-000000")

from app.engine.calculator import PayrollEngine  # noqa: E402
from app.engine.types import (  # noqa: E402
    EarningLine,
    EarningType,
    PayFrequency,
    PayrollInput,
    TaxBasis,
    TaxProfile,
    UscStatus,
    YearToDate,
)
from app.rules.repository import RuleRepository  # noqa: E402

D = Decimal


@pytest.fixture(scope="session")
def repo() -> RuleRepository:
    return RuleRepository.from_directory()


@pytest.fixture(scope="session")
def engine(repo) -> PayrollEngine:
    return PayrollEngine(repo)


def profile(basis=TaxBasis.CUMULATIVE, credits="4000", srcop="44000", usc=UscStatus.ORDINARY, ppsn=True, rpn=True, **kw):
    return TaxProfile(tax_basis=basis, annual_tax_credits=D(credits) if credits is not None else None,
                      annual_srcop=D(srcop) if srcop is not None else None, usc_status=usc, ppsn_present=ppsn,
                      rpn_present=rpn, rpn_number="RPN1" if rpn else None, **kw)


def make_input(pay="4000", freq=PayFrequency.MONTHLY, period=1, pay_date=None, prsi="A", prof=None, ytd=None,
               earnings=None, **kw) -> PayrollInput:
    if pay_date is None:
        pay_date = date(2026, period, 25) if freq == PayFrequency.MONTHLY else date(2026, 1, 2)
    return PayrollInput(employee_ref="T1", tax_year=pay_date.year, frequency=freq, period_number=period, payment_date=pay_date,
                        prsi_class=prsi, tax_profile=prof or profile(), ytd=ytd or YearToDate(),
                        earnings=earnings if earnings is not None else [EarningLine(EarningType.BASIC, D(pay))], **kw)


def run_year(engine, monthly_pay: str, prof=None, periods=12, **kw):
    """Run consecutive monthly periods carrying YTD forward, like a real payroll."""
    ytd = YearToDate()
    out = []
    for m in range(1, periods + 1):
        r = engine.calculate(make_input(monthly_pay, period=m, prof=prof, ytd=ytd, **kw))
        assert r.status.value == "CALCULATED", r.error_message
        out.append(r)
        ytd = r.new_ytd
    return out
