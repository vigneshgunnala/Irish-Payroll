"""USC and PRSI engine tests.

USC 2026 bands: Revenue "Standard rates and thresholds of USC" - 0.5% to €12,012; 2% to €28,700; 3% to €70,044; 8% balance.
PRSI: DSP SW14 (January 2026) and Advance Notice 2026. The weekly €377 credit example is DSP's own worked example.
"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.engine.types import PayFrequency, TaxBasis, UscStatus
from tests.conftest import make_input, profile, run_year

W = PayFrequency.WEEKLY
JAN = date(2026, 1, 9)
OCT = date(2026, 10, 2)


# ------------------------------------------------------------------ USC


def test_usc_monthly_period_1(engine):
    # bands per month: 1,001.00 | 2,391.67 | 5,837.00
    # 1,001.00@0.5% = 5.01 ; 1,390.67@2% = 27.81 ; 1,608.33@3% = 48.25 → 81.07
    r = engine.calculate(make_input("4000"))
    assert r.usc == D("81.07")
    bands = [t for t in r.trace if t.component == "USC" and t.step.startswith("Band")]
    assert [b.result for b in bands] == [D("5.01"), D("27.81"), D("48.25"), D("0.00")]


def test_usc_full_year_matches_annual(engine):
    # 60,000: 12,012@0.5%=60.06 ; 16,688@2%=333.76 ; 31,300@3%=939.00 → 1,332.82
    total = sum(r.usc for r in run_year(engine, "5000"))
    assert abs(total - D("1332.82")) <= D("0.30")


def test_usc_8pct_band(engine):
    # 100,000: 60.06 + 333.76 + 41,344@3%=1,240.32 + 29,956@8%=2,396.48 → 4,030.62
    total = sum(r.usc for r in run_year(engine, str((D("100000") / 12).quantize(D("0.01")))))
    assert abs(total - D("4030.62")) <= D("0.40")


def test_usc_exempt(engine):
    r = engine.calculate(make_input("1000", prof=profile(usc=UscStatus.EXEMPT)))
    assert r.usc == 0 and r.usc_status_applied == "EXEMPT"


def test_usc_reduced(engine):
    # reduced: 0.5% to 1,001.00, 2% on balance → 5.01 + 59.98 = 64.99
    r = engine.calculate(make_input("4000", prof=profile(usc=UscStatus.REDUCED)))
    assert r.usc == D("64.99")


def test_usc_non_cumulative(engine):
    r = engine.calculate(make_input("4000", period=6, prof=profile(basis=TaxBasis.WEEK1_MONTH1)))
    assert r.usc == D("81.07")


def test_usc_not_relieved_by_pension(engine):
    from app.engine.types import PensionContribution, PensionScheme
    r = engine.calculate(make_input("4000", pensions=[PensionContribution(PensionScheme.OCCUPATIONAL, D("200"))],
                                    date_of_birth=date(1990, 1, 1)))
    assert r.pay_for_usc == D("4000.00") and r.pay_for_tax == D("3800.00")
    assert r.usc == D("81.07")


def test_usc_missing_status_blocks(engine):
    r = engine.calculate(make_input("4000", prof=profile(usc=None)))
    assert r.error_code == "USC_STATUS_MISSING"


def test_usc_2025_rules_differ_from_2026(repo):
    """A 2026 change must not alter 2025: the 2% ceiling is €27,382 in 2025 and €28,700 in 2026."""
    b25 = repo.get("USC", "standard_bands", date(2025, 6, 1)).value
    b26 = repo.get("USC", "standard_bands", date(2026, 6, 1)).value
    assert b25[1]["upper"] == "27382" and b26[1]["upper"] == "28700"


def test_2025_payroll_blocked_without_verified_prsi(engine):
    r = engine.calculate(make_input("4000", pay_date=date(2025, 1, 24)))
    assert r.status.value == "MISSING" and r.error_code == "RULE_MISSING"


# ------------------------------------------------------------------ PRSI Class A


def test_dsp_prsi_credit_worked_example(engine):
    """DSP Advance Notice 2026: €377/week → credit €12 − (377 − 352.01)/6 = €7.83; 4.2% = €15.83; charge €8.00."""
    r = engine.calculate(make_input("377", freq=W, pay_date=JAN))
    assert r.prsi_ee == D("8.00")
    assert r.prsi_subclass == "AX"
    credit = next(t for t in r.trace if t.step == "PRSI credit")
    assert credit.result == D("7.83")


def test_prsi_credit_example_after_1_october(engine):
    # 4.35% × 377 = 16.40 ; credit unchanged 7.83 → 8.57 ; employer 9.15% = 34.50
    r = engine.calculate(make_input("377", freq=W, period=40, pay_date=OCT))
    assert r.prsi_ee == D("8.57")
    assert r.prsi_er == D("34.50")


@pytest.mark.parametrize("pay, ee, er, sub", [
    ("352.00", "0.00", "31.68", "A0"),     # employee nil; employer 9%
    ("424.01", "17.81", "38.16", "AL"),    # above credit band: 4.2% on all, no credit
    ("552.00", "23.18", "49.68", "AL"),    # employer lower rate up to €552
    ("552.01", "23.18", "62.10", "A1"),    # employer higher rate 11.25% on ALL pay
    ("1000.00", "42.00", "112.50", "A1"),
])
def test_prsi_class_a_weekly_thresholds(engine, pay, ee, er, sub):
    r = engine.calculate(make_input(pay, freq=W, pay_date=JAN))
    assert (r.prsi_ee, r.prsi_er, r.prsi_subclass) == (D(ee), D(er), sub)


def test_prsi_below_38_is_class_j(engine):
    r = engine.calculate(make_input("30", freq=W, pay_date=JAN))
    assert r.prsi_class == "J" and r.prsi_ee == 0 and r.prsi_er == D("0.21")  # 0.70%


def test_prsi_below_38_after_october_class_j(engine):
    """SW14: J0 employer rate 0.85% from 1 October 2026 → 30 × 0.85% = 0.255 → €0.26."""
    r = engine.calculate(make_input("30", freq=W, period=40, pay_date=OCT))
    assert r.prsi_class == "J" and r.prsi_er == D("0.26") and "PRSI-2026-J-H2" in r.rules_used


def test_prsi_monthly_thresholds_scale_52_over_12(engine):
    # SW14 monthly bands: A0 to €1,525; AL to €2,392
    assert engine.calculate(make_input("1525")).prsi_ee == 0
    r = engine.calculate(make_input("2392"))
    assert r.prsi_er == D("215.28") and r.prsi_subclass == "AL"   # 9%
    r = engine.calculate(make_input("2392.01"))
    assert r.prsi_er == D("269.10") and r.prsi_subclass == "A1"   # 11.25%


def test_prsi_monthly_credit(engine):
    # monthly credit band 1,525.38–1,837.33, max €52.00
    r = engine.calculate(make_input("1600"))
    # 4.2% × 1,600 = 67.20 ; credit 52.00 − (1,600 − 1,525.38)/6 = 52.00 − 12.44 = 39.56 → 27.64
    assert r.prsi_ee == D("27.64")


def test_prsi_rate_switch_on_1_october_by_pay_date(engine):
    sep = engine.calculate(make_input("4000", period=9, pay_date=date(2026, 9, 25)))
    octo = engine.calculate(make_input("4000", period=10, pay_date=date(2026, 10, 23)))
    assert sep.prsi_ee == D("168.00") and octo.prsi_ee == D("174.00")
    assert sep.prsi_er == D("450.00") and octo.prsi_er == D("456.00")
    assert "PRSI-2026-A-H1" in sep.rules_used and "PRSI-2026-A-H2" in octo.rules_used


# ------------------------------------------------------------------ other classes


def test_class_s_no_employer_share(engine):
    r = engine.calculate(make_input("8000", prsi="S"))
    assert r.prsi_ee == D("336.00") and r.prsi_er == 0 and r.prsi_subclass == "S1"


def test_class_m_nil(engine):
    r = engine.calculate(make_input("4000", prsi="M"))
    assert r.prsi_ee == 0 and r.prsi_er == 0


def test_class_j_over_pension_age(engine):
    r = engine.calculate(make_input("4000", prsi="J"))
    assert r.prsi_ee == 0 and r.prsi_er == D("28.00")


def test_class_b_before_october(engine):
    # weekly 1,600: 1,443@1.1% = 15.87 + 157@4.2% = 6.59 → 22.46 ; employer 2.21% = 35.36
    r = engine.calculate(make_input("1600", freq=W, pay_date=JAN, prsi="B"))
    assert r.prsi_ee == D("22.46") and r.prsi_er == D("35.36")


def test_class_b_after_october(engine):
    # SW14 from 1 Oct 2026: first €1,443 @1.25% = 18.04 + 157 @4.35% = 6.83 → 24.87 ; employer 2.36% = 37.76
    r = engine.calculate(make_input("1600", freq=W, period=40, pay_date=OCT, prsi="B"))
    assert r.prsi_ee == D("24.87") and r.prsi_er == D("37.76")


def test_unverified_rule_blocks_calculation(repo):
    """If any rule the calculation needs is not VERIFIED, the employee is not calculated."""
    from dataclasses import replace

    from app.engine.calculator import PayrollEngine
    from app.rules.repository import RuleRepository
    rules = [replace(r, status="UNVERIFIED") if r.rule_id == "PRSI-2026-A-H2" else r for r in repo.rules]
    r = PayrollEngine(RuleRepository.from_rules(rules)).calculate(make_input("4000", period=10, pay_date=date(2026, 10, 23)))
    assert r.status.value == "UNVERIFIED" and "PRSI-2026-A-H2" in r.error_message


def test_class_h_credit(engine):
    r = engine.calculate(make_input("377", freq=W, pay_date=JAN, prsi="H"))
    assert r.prsi_ee == D("7.63")  # 4.10% × 377 = 15.46 − 7.83


def test_class_k_threshold(engine):
    assert engine.calculate(make_input("90", freq=W, pay_date=JAN, prsi="K")).prsi_ee == 0
    assert engine.calculate(make_input("500", freq=W, pay_date=JAN, prsi="K")).prsi_ee == D("21.00")


def test_missing_prsi_class_blocks(engine):
    r = engine.calculate(make_input("4000", prsi=None))
    assert r.error_code == "PRSI_CLASS_MISSING"
    assert "cannot be confirmed" in r.error_message


def test_unsupported_prsi_class(engine):
    assert engine.calculate(make_input("4000", prsi="Z")).error_code == "PRSI_CLASS_INVALID"
