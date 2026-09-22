"""PAYE engine tests.

Expected values are derived by hand from the 2026 rates/bands on Revenue's tax relief charts
(https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx):
standard rate 20% on the first €44,000 (single), 40% on the balance; credits from the RPN.
Period figures use Revenue's round-up-to-the-cent convention (e.g. €44,000/12 = €3,666.67; €4,000/12 = €333.34).
"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.engine.types import EarningLine, EarningType, PayFrequency, TaxBasis, YearToDate
from tests.conftest import make_input, profile, run_year


def test_standard_monthly_period_1(engine):
    # 3,666.67 @20% = 733.33 ; 333.33 @40% = 133.33 ; 866.66 - 333.34 credits = 533.32
    r = engine.calculate(make_input("4000"))
    assert r.gross_tax == D("866.66")
    assert r.paye == D("533.32")


def test_low_income_no_tax(engine):
    r = engine.calculate(make_input("1500"))
    assert r.paye == D("0.00")  # 300.00 gross tax < 333.34 credits


def test_high_income(engine):
    # 3,666.67@20%=733.33 ; 11,333.33@40%=4,533.33 ; 5,266.66-333.34 = 4,933.32
    r = engine.calculate(make_input("15000"))
    assert r.paye == D("4933.32")


@pytest.mark.parametrize("salary, annual_tax", [
    ("60000", D("11200")),   # 44,000@20% + 16,000@40% - 4,000
    ("30000", D("2000")),    # 30,000@20% - 4,000
    ("120000", D("35200")),  # 8,800 + 76,000@40%=30,400 → 39,200 - 4,000
])
def test_cumulative_full_year_matches_annual_liability(engine, salary, annual_tax):
    monthly = (D(salary) / 12).quantize(D("0.01"))
    results = run_year(engine, str(monthly))
    total = sum(r.paye for r in results)
    # period rounding (cut-off/credits rounded up to the cent) moves the annual figure by cents only
    assert abs(total - annual_tax) <= D("0.30"), total
    # equal pay → essentially equal deduction each month
    assert max(r.paye for r in results) - min(r.paye for r in results) <= D("0.05")


def test_cumulative_uses_previous_ytd(engine):
    ytd = YearToDate(pay_for_tax=D("32000"), tax=D("4266.56"))  # 8 months of €4,000
    r = engine.calculate(make_input("4000", period=9, ytd=ytd))
    # cum pay 36,000; cut-off 3,666.67*9 = 33,000.03 → 6,600.01 + 2,999.97*0.4=1,199.99 = 7,800.00; credits 3,000.06
    assert r.gross_tax == D("7800.00")
    assert r.paye == D("7800.00") - D("3000.06") - D("4266.56")


def test_refund_on_cumulative_basis(engine):
    # previous over-deduction → negative PAYE (refund) and INFO message
    ytd = YearToDate(pay_for_tax=D("4000"), tax=D("1500"))
    r = engine.calculate(make_input("0", period=2, ytd=ytd, earnings=[]))
    assert r.paye < 0
    assert any(m["code"] == "PAYE_REFUND" for m in r.messages)


def test_week1_ignores_ytd(engine):
    ytd = YearToDate(pay_for_tax=D("50000"), tax=D("100"))
    r = engine.calculate(make_input("4000", period=9, prof=profile(basis=TaxBasis.WEEK1_MONTH1), ytd=ytd))
    assert r.paye == D("533.32")
    assert r.tax_basis_applied == "WEEK1_MONTH1"


def test_mid_year_joiner_with_previous_employment(engine):
    # joins in month 7; RPN shows €24,000 pay and €2,800 tax from previous employer
    prof = profile(prior_pay_for_tax=D("24000"), prior_tax=D("2800"))
    r = engine.calculate(make_input("4000", period=7, prof=prof))
    cum_pay = D("28000")
    std = (D("3666.67") * 7).min(cum_pay)
    gross = (std * D("0.2")).quantize(D("0.01")) + ((cum_pay - std) * D("0.4")).quantize(D("0.01"))
    assert r.paye == gross - D("333.34") * 7 - D("2800")


def test_salary_change_mid_year(engine):
    ytd = YearToDate()
    total = D(0)
    for m in range(1, 13):
        pay = "3000" if m <= 6 else "6000"
        r = engine.calculate(make_input(pay, period=m, ytd=ytd))
        ytd, total = r.new_ytd, total + r.paye
    # annual pay 54,000 → 8,800 + 10,000*0.4 - 4,000 = 8,800
    assert abs(total - D("8800")) <= D("0.30")


# --------------------------------------------------------------- emergency basis
# Source: Revenue "The Emergency Basis of Tax & USC Deduction" (emergency-rates.pdf), 2026 table.


def test_emergency_no_ppsn_all_higher_rate(engine):
    r = engine.calculate(make_input("1000", freq=PayFrequency.WEEKLY, prof=profile(ppsn=False, rpn=False)))
    assert r.tax_basis_applied == "EMERGENCY"
    assert r.paye == D("400.00")
    assert r.usc == D("80.00")  # emergency USC 8% on all pay
    assert "No PPSN" in next(t for t in r.trace if t.step == "Basis selection").calculation


def test_emergency_with_ppsn_weeks_1_to_4_then_higher_rate(engine):
    prof = profile(ppsn=True, rpn=False)
    ytd = YearToDate()
    taxes = []
    for w in range(1, 7):
        r = engine.calculate(make_input("1000", freq=PayFrequency.WEEKLY, period=w, prof=prof, ytd=ytd,
                                        pay_date=date(2026, 1, 2 + 7 * (w - 1)) if w < 5 else date(2026, 2, 6)))
        ytd = r.new_ytd
        taxes.append(r.paye)
    # weeks 1-4: 846.16@20% = 169.23 + 153.84@40% = 61.54 → 230.77, no credits
    assert taxes[:4] == [D("230.77")] * 4
    assert taxes[4:] == [D("400.00")] * 2


def test_emergency_monthly_month_1_cut_off(engine):
    prof = profile(ppsn=True, rpn=False)
    r1 = engine.calculate(make_input("4000", prof=prof))
    assert r1.paye == D("733.33") + D("133.33")  # 3,666.67@20% + 333.33@40%, no credits
    r2 = engine.calculate(make_input("4000", period=2, prof=prof, ytd=r1.new_ytd))
    assert r2.paye == D("1600.00")


def test_emergency_fortnightly_is_blocked_not_guessed(engine):
    r = engine.calculate(make_input("2000", freq=PayFrequency.FORTNIGHTLY, prof=profile(rpn=False), pay_date=date(2026, 1, 9)))
    assert r.status.value == "UNVERIFIED"
    assert r.error_code == "EMERGENCY_FREQ_UNVERIFIED"


def test_rpn_instructed_emergency(engine):
    r = engine.calculate(make_input("4000", prof=profile(basis=TaxBasis.EMERGENCY)))
    assert r.tax_basis_applied == "EMERGENCY"


# --------------------------------------------------------------- refusal to guess


def test_missing_rpn_credits_blocks(engine):
    r = engine.calculate(make_input("4000", prof=profile(credits=None)))
    assert r.status.value == "MISSING"
    assert "Unable to calculate reliably" in r.error_message


def test_missing_tax_basis_blocks(engine):
    r = engine.calculate(make_input("4000", prof=profile(basis=None)))
    assert r.error_code == "TAX_BASIS_MISSING"


def test_trace_explains_paye(engine):
    r = engine.calculate(make_input("4000"))
    steps = [t.step for t in r.trace if t.component == "PAYE"]
    assert steps[:3] == ["Basis selection", "Periodise RPN", "Cumulative pay"]
    assert "Standard-rate portion" in steps and "Higher-rate portion" in steps and "PAYE due" in steps
    std = next(t for t in r.trace if t.step == "Standard-rate portion")
    assert std.rule["source_url"].startswith("https://www.revenue.ie/")
    assert std.rule["status"] == "VERIFIED"


def test_married_one_income(engine):
    r = engine.calculate(make_input("5000", prof=profile(credits="6000", srcop="53000")))
    # 53,000/12 = 4,416.67@20% = 883.33 ; 583.33@40% = 233.33 ; - 500.00
    assert r.paye == D("616.66")


def test_multiple_earnings_types(engine):
    earnings = [EarningLine(EarningType.BASIC, D("3000")), EarningLine(EarningType.OVERTIME, D("400")),
                EarningLine(EarningType.BONUS, D("500")), EarningLine(EarningType.COMMISSION, D("100"))]
    r = engine.calculate(make_input(earnings=earnings))
    assert r.gross_pay == D("4000.00")
    assert r.paye == D("533.32")
