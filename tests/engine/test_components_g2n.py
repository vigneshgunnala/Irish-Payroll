"""LPT, pension, BIK and gross-to-net tests.

BIK car: Revenue 'How to calculate the taxable benefit' - 2026 OMV reduction €10,000 (A1-D), extra €20,000 for A1,
business-km percentage table. Medical insurance: BIK = gross premium. Small benefit: 5 benefits / €1,500 per year.
Pension: Revenue age-related limits (15%-40%) and €115,000 earnings cap; no USC/PRSI relief.
"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.engine.types import (
    BenefitLine,
    BenefitType,
    Deduction,
    EarningLine,
    EarningType,
    PensionContribution,
    PensionScheme,
    YearToDate,
)
from tests.conftest import make_input, profile, run_year

# ------------------------------------------------------------------ LPT


def test_lpt_spread_equally(engine):
    r = engine.calculate(make_input("4000", prof=profile(lpt_annual=D("315"))))
    assert r.lpt == D("26.25")
    assert r.statutory_liability == r.paye + r.usc + r.prsi_ee + r.prsi_er + D("26.25")


def test_lpt_final_period_trues_up(engine):
    results = run_year(engine, "4000", prof=profile(lpt_annual=D("225")))
    assert sum(r.lpt for r in results) == D("225.00")


def test_no_lpt_without_rpn_instruction(engine):
    assert engine.calculate(make_input("4000")).lpt == 0


# ------------------------------------------------------------------ pension


def _pens(ee, scheme=PensionScheme.OCCUPATIONAL, er="0"):
    return [PensionContribution(scheme, D(ee), D(er))]


def test_pension_relieves_paye_only(engine):
    r = engine.calculate(make_input("4000", pensions=_pens("200", er="200"), date_of_birth=date(1985, 5, 1)))
    assert r.pay_for_tax == D("3800.00") and r.pay_for_usc == D("4000.00") and r.pay_for_prsi == D("4000.00")
    assert r.pension_ee == D("200.00") and r.pension_er == D("200.00")
    assert r.net_pay == D("4000") - r.paye - r.usc - r.prsi_ee - D("200")
    assert r.employer_cost == D("4000") + r.prsi_er + D("200")


def test_pension_age_limit_caps_relief(engine):
    # age 25 → 15% × 48,000 annualised = 7,200 p.a.; monthly contribution 1,000 → full year would exceed
    ytd = YearToDate(pension_relieved=D("6800"))
    r = engine.calculate(make_input("4000", period=8, ytd=ytd, pensions=_pens("1000"), date_of_birth=date(2001, 1, 1)))
    assert r.pay_for_tax == D("3600.00")  # only 400 relieved
    assert any(m["code"] == "PENSION_LIMIT_EXCEEDED" for m in r.messages)


def test_pension_earnings_cap(engine):
    # 60+: 40% × min(240,000, 115,000) = 46,000 limit
    step_ok = engine.calculate(make_input("20000", pensions=_pens("3000"), date_of_birth=date(1960, 1, 1)))
    limit = next(t for t in step_ok.trace if t.step == "Relief limit")
    assert "€46,000.00" in limit.calculation


def test_rac_not_relieved_through_payroll(engine):
    r = engine.calculate(make_input("4000", pensions=_pens("100", PensionScheme.RAC), date_of_birth=date(1980, 1, 1)))
    assert r.pay_for_tax == D("4000.00") and r.pension_ee == D("100.00")


def test_pension_needs_dob(engine):
    r = engine.calculate(make_input("4000", pensions=_pens("100")))
    assert r.error_code == "DOB_MISSING"


# ------------------------------------------------------------------ BIK


def car(omv, co2, km, contrib="0"):
    return BenefitLine(BenefitType.COMPANY_CAR, "car", omv=D(omv), co2_g_km=D(co2), business_km=km,
                       employee_contribution_annual=D(contrib))


@pytest.mark.parametrize("omv, co2, km, contrib, monthly", [
    ("45000", "135", 22000, "0", "875.00"),      # C: (45,000-10,000) × 30% = 10,500
    ("45000", "135", 41000, "1200", "425.00"),   # C 39,001-48,000 → 18% = 6,300 - 1,200 = 5,100
    ("45000", "0", 12000, "0", "187.50"),        # A1: (45,000-30,000) × 15% = 2,250
    ("61000", "190", 52000, "0", "762.50"),      # E: no reduction, 48,001+ → 15% = 9,150
    ("25000", "0", 10000, "0", "0.00"),          # A1 reduced OMV floored at zero
])
def test_company_car_bik(engine, omv, co2, km, contrib, monthly):
    r = engine.calculate(make_input("4000", benefits=[car(omv, co2, km, contrib)]))
    assert r.bik == D(monthly)


def test_bik_adds_to_tax_usc_prsi_but_not_cash(engine):
    base = engine.calculate(make_input("4000"))
    r = engine.calculate(make_input("4000", benefits=[car("45000", "135", 22000)]))
    assert r.pay_for_tax == r.pay_for_usc == r.pay_for_prsi == D("4875.00")
    assert r.gross_pay == D("4000.00")
    assert r.paye > base.paye and r.usc > base.usc and r.prsi_ee > base.prsi_ee
    assert r.net_pay == D("4000") - r.paye - r.usc - r.prsi_ee


def test_medical_insurance_gross_premium(engine):
    r = engine.calculate(make_input("4000", benefits=[BenefitLine(BenefitType.MEDICAL_INSURANCE, annual_value=D("1780"))]))
    assert r.bik == D("148.33")


def test_small_benefit_exemption(engine):
    sb = [BenefitLine(BenefitType.SMALL_BENEFIT, "voucher", value=D("500"))]
    assert engine.calculate(make_input("4000", benefits=sb)).bik == 0
    used = YearToDate(small_benefit_count=5, small_benefit_value=D("1000"))
    r = engine.calculate(make_input("4000", period=11, ytd=used, benefits=sb))
    assert r.bik == D("500.00")  # 6th benefit fully taxable
    used = YearToDate(small_benefit_count=2, small_benefit_value=D("1200"))
    assert engine.calculate(make_input("4000", period=11, ytd=used, benefits=sb)).bik == D("500.00")  # would exceed €1,500


def test_car_bik_missing_data_blocks(engine):
    r = engine.calculate(make_input("4000", benefits=[BenefitLine(BenefitType.COMPANY_CAR, omv=D("30000"))]))
    assert r.error_code == "BIK_CAR_DATA_MISSING"


# ------------------------------------------------------------------ gross to net


def test_gross_to_net_identities(engine):
    r = engine.calculate(make_input("5200", prof=profile(lpt_annual=D("405")), pensions=_pens("260", er="312"),
                                    deductions=[Deduction("UNION", D("18.50"))], date_of_birth=date(1979, 3, 3),
                                    benefits=[BenefitLine(BenefitType.MEDICAL_INSURANCE, annual_value=D("2240"))]))
    assert r.net_pay == r.gross_pay - r.paye - r.usc - r.prsi_ee - r.lpt - r.pension_ee - r.other_deductions
    assert r.employer_cost == r.gross_pay + r.prsi_er + r.pension_er + r.bik
    assert r.statutory_liability == r.paye + r.usc + r.prsi_ee + r.prsi_er + r.lpt


def test_zero_pay(engine):
    r = engine.calculate(make_input("0", earnings=[]))
    assert r.status.value == "CALCULATED" and r.net_pay == 0 and r.prsi_ee == 0


def test_negative_adjustment_allowed_negative_bonus_rejected(engine):
    ok = engine.calculate(make_input(earnings=[EarningLine(EarningType.BASIC, D("4000")),
                                               EarningLine(EarningType.ADJUSTMENT, D("-250"))]))
    assert ok.gross_pay == D("3750.00")
    bad = engine.calculate(make_input(earnings=[EarningLine(EarningType.BONUS, D("-10"))]))
    assert bad.status.value == "INVALID"


def test_negative_gross_rejected(engine):
    r = engine.calculate(make_input(earnings=[EarningLine(EarningType.ADJUSTMENT, D("-10"))]))
    assert r.error_code == "NEGATIVE_GROSS"


def test_negative_net_flagged(engine):
    r = engine.calculate(make_input("500", deductions=[Deduction("ADVANCE", D("800"))]))
    assert r.net_pay < 0 and any(m["code"] == "NEGATIVE_NET" and m["severity"] == "ERROR" for m in r.messages)


def test_tax_year_mismatch(engine):
    inp = make_input("4000", pay_date=date(2027, 1, 5))
    inp.tax_year = 2026
    assert engine.calculate(inp).error_code == "TAX_YEAR_MISMATCH"


def test_every_rule_in_trace_is_verified_and_sourced(engine):
    r = engine.calculate(make_input("5000", prof=profile(lpt_annual=D("315")), pensions=_pens("250"),
                                    date_of_birth=date(1970, 1, 1), benefits=[car("40000", "110", 30000)]))
    refs = [t.rule for t in r.trace if t.rule]
    assert refs and all(x["status"] == "VERIFIED" and x["source_url"].startswith("https://") for x in refs)


def test_irregular_pay_pattern_cumulative_catches_up(engine):
    ytd, total = YearToDate(), D(0)
    pays = ["4000", "0", "8000", "2000", "6000", "4000", "4000", "4000", "4000", "4000", "4000", "4000"]
    for m, p in enumerate(pays, start=1):
        r = engine.calculate(make_input(p, period=m, ytd=ytd, earnings=[EarningLine(EarningType.BASIC, D(p))]))
        ytd, total = r.new_ytd, total + r.paye
    # annual 48,000 → 8,800 + 1,600 - 4,000 = 6,400
    assert abs(total - D("6400")) <= D("0.30")
