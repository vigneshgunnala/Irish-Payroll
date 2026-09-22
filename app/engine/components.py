"""LPT, pension and BIK component engines. Each is independent and traced."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.engine.context import CalcContext
from app.engine.money import ZERO, D, fmt, money, pct
from app.engine.types import BenefitLine, BenefitType, CalculationBlocked, PensionScheme

# --------------------------------------------------------------------------- LPT


def calculate_lpt(ctx: CalcContext) -> Decimal:
    """Deduct only what the RPN instructs, spread equally; final period trues up to the exact annual amount."""
    annual = ctx.inp.tax_profile.lpt_annual
    if not annual or annual <= 0:
        return ZERO
    rule = ctx.rule("LPT", "deduction_method")
    n, ppy = ctx.inp.period_number, ctx.ppy
    if n >= ppy:
        amt = max(annual - ctx.inp.ytd.lpt, ZERO)
        calc = f"final period: {fmt(annual)} − {fmt(ctx.inp.ytd.lpt)} already deducted"
    else:
        amt = money(annual / ppy)
        calc = f"{fmt(annual)} ÷ {ppy}"
    ctx.add("LPT", "LPT deduction", "Local Property Tax per RPN instruction (spread equally over the year)",
            calc, amt, {"annual_lpt_on_rpn": annual}, rule=rule)
    return amt


# --------------------------------------------------------------------------- Pension


def _age(dob: date, on: date) -> int:
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def calculate_pension(ctx: CalcContext, gross_cash: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Returns (employee_total, employer_total, amount relieved for PAYE)."""
    inp = ctx.inp
    if not inp.pensions:
        return ZERO, ZERO, ZERO
    treat_rule = ctx.rule("PENSION", "employee_contribution_treatment")
    ee_total = sum((p.employee_amount for p in inp.pensions), ZERO)
    er_total = sum((p.employer_amount for p in inp.pensions), ZERO)
    relievable = ZERO
    for p in inp.pensions:
        t = treat_rule.value[p.scheme.value]
        if t["relieve_paye"]:
            relievable += p.employee_amount
        ctx.add("PENSION", f"{p.scheme.value} contribution",
                "Treatment of employee contribution (net pay arrangement)",
                f"employee {fmt(p.employee_amount)}: PAYE relief {'yes' if t['relieve_paye'] else 'no'}, "
                f"USC relief {'yes' if t['relieve_usc'] else 'no'}, PRSI relief {'yes' if t['relieve_prsi'] else 'no'}; "
                f"employer {fmt(p.employer_amount)}", p.employee_amount, rule=treat_rule)
        if p.scheme == PensionScheme.RAC and p.employee_amount > 0:
            ctx.warn("PENSION_RAC_NO_PAYROLL_RELIEF",
                     "RAC premium deducted from net pay; relief must be claimed by the employee directly.", "INFO")

    if relievable <= 0:
        return ee_total, er_total, ZERO
    if inp.date_of_birth is None:
        raise CalculationBlocked("DOB_MISSING", "Pension relief limit cannot be confirmed: date of birth missing.")
    limits = ctx.rule("PENSION", "age_related_limits")
    cap_rule = ctx.rule("PENSION", "earnings_cap")
    age = _age(inp.date_of_birth, inp.payment_date)
    percent = ZERO
    for band in limits.value:
        if age >= band["min_age"]:
            percent = D(band["percent"])
    annualised = money(gross_cash * ctx.ppy)
    annual_limit = money(min(annualised, D(cap_rule.value)) * percent)
    remaining = max(annual_limit - inp.ytd.pension_relieved, ZERO)
    relieved = min(relievable, remaining)
    ctx.add("PENSION", "Relief limit", "Age-related limit on annualised earnings (capped)",
            f"age {age} → {pct(percent)} × min({fmt(annualised)}, {fmt(cap_rule.value)}) = {fmt(annual_limit)}; "
            f"remaining {fmt(remaining)}", relieved, rule=limits)
    if relieved < relievable:
        ctx.warn("PENSION_LIMIT_EXCEEDED",
                 f"Employee pension {fmt(relievable)} exceeds the remaining relief limit; only {fmt(relieved)} "
                 "relieved through payroll.")
    return ee_total, er_total, relieved


# --------------------------------------------------------------------------- BIK


def _car_category(ctx: CalcContext, co2: Decimal) -> str:
    cats = ctx.rule("BIK", "car_co2_categories")
    for c in cats.value:
        if c["max_co2"] is None or co2 <= D(c["max_co2"]):
            return c["code"]
    return cats.value[-1]["code"]


def _value_car(ctx: CalcContext, b: BenefitLine) -> Decimal:
    if b.omv is None or b.co2_g_km is None or b.business_km is None:
        raise CalculationBlocked("BIK_CAR_DATA_MISSING", "Company car BIK needs OMV, CO2 and business kilometres.")
    cat = _car_category(ctx, D(b.co2_g_km))
    red_rule = ctx.rule("BIK", "car_omv_reduction")
    reduction = D(red_rule.value.get(cat, "0"))
    if cat == "A1":
        ev = ctx.rule("BIK", "car_ev_additional_reduction")
        reduction += D(ev.value)
    reduced_omv = max(D(b.omv) - reduction, ZERO)
    table = ctx.rule("BIK", "car_business_km_percentages")
    rate = ZERO
    for row in table.value:
        if row["max_km"] is None or b.business_km <= row["max_km"]:
            rate = D(row[cat])
            break
    annual = max(money(reduced_omv * rate) - D(b.employee_contribution_annual), ZERO)
    period = money(annual / ctx.ppy)
    ctx.add("BIK", "Company car", f"Category {cat} ({b.co2_g_km} g/km), {b.business_km:,} business km",
            f"({fmt(b.omv)} − {fmt(reduction)} OMV reduction) × {pct(rate)} − {fmt(b.employee_contribution_annual)} "
            f"employee contribution = {fmt(annual)} p.a. ÷ {ctx.ppy}", period,
            {"category": cat, "annual_cash_equivalent": annual}, pct(rate), table)
    return period


def calculate_bik(ctx: CalcContext) -> tuple[Decimal, int, Decimal]:
    """Returns (taxable notional pay this period, small benefits used, small benefit value used)."""
    total = ZERO
    sb_count, sb_value = 0, ZERO
    for b in ctx.inp.benefits:
        if b.type == BenefitType.COMPANY_CAR:
            total += _value_car(ctx, b)
        elif b.type == BenefitType.MEDICAL_INSURANCE:
            r = ctx.rule("BIK", "medical_insurance_valuation")
            if b.annual_value is None:
                raise CalculationBlocked("BIK_MEDICAL_MISSING", "Medical insurance BIK needs the gross annual premium.")
            amt = money(D(b.annual_value) / ctx.ppy)
            ctx.add("BIK", "Medical insurance", "Gross premium (before TRS) is the taxable benefit",
                    f"{fmt(b.annual_value)} ÷ {ctx.ppy}", amt, rule=r)
            total += amt
        elif b.type == BenefitType.SMALL_BENEFIT:
            r = ctx.rule("BIK", "small_benefit_exemption")
            val = D(b.value)
            used_c = ctx.inp.ytd.small_benefit_count + sb_count
            used_v = ctx.inp.ytd.small_benefit_value + sb_value
            if used_c < int(r.value["max_count"]) and used_v + val <= D(r.value["max_value"]):
                sb_count += 1
                sb_value += val
                ctx.add("BIK", "Small benefit", "Exempt under the small benefit exemption",
                        f"benefit {used_c + 1} of {r.value['max_count']}; {fmt(used_v + val)} ≤ {fmt(r.value['max_value'])}",
                        ZERO, rule=r)
            else:
                total += money(val)
                ctx.add("BIK", "Small benefit", "Exemption exhausted - full value is taxable",
                        f"count used {used_c}, value used {fmt(used_v)}", val, rule=r)
                ctx.warn("SMALL_BENEFIT_EXHAUSTED", "Small benefit exemption exhausted; benefit taxed in full.")
        else:
            if b.period_value is None:
                raise CalculationBlocked("BIK_VALUE_MISSING", f"Benefit '{b.description}' has no cash-equivalent value.")
            amt = money(b.period_value)
            ctx.add("BIK", "Other benefit", f"{b.description or 'Other benefit'} (cash equivalent valued outside the engine)",
                    fmt(amt), amt, rule=ctx.rule("BIK", "notional_pay_treatment"))
            total += amt
    return total, sb_count, sb_value
