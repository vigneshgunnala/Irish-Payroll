"""PAYE (income tax) engine: cumulative, Week 1 / Month 1 and emergency bases.

Flow exposed in the trace:
    pay for tax -> (cumulative) pay -> standard-rate portion -> higher-rate portion
    -> gross tax -> tax credits -> net tax -> tax already deducted -> PAYE this period
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.engine.context import CalcContext
from app.engine.money import ZERO, D, fmt, money, pct
from app.engine.types import CalcStatus, CalculationBlocked, PayFrequency, TaxBasis

C = "PAYE"


@dataclass
class PayeOutcome:
    paye: Decimal
    gross_tax: Decimal
    credits: Decimal
    basis: TaxBasis
    emergency_period_index: int = 0


def _tax_on(ctx: CalcContext, pay: Decimal, srcop: Decimal, credits: Decimal, label: str) -> tuple[Decimal, Decimal]:
    std_rule = ctx.rule(C, "standard_rate")
    high_rule = ctx.rule(C, "higher_rate")
    std_rate, high_rate = D(std_rule.value), D(high_rule.value)
    pay = max(pay, ZERO)
    at_std = min(pay, srcop)
    at_high = max(pay - srcop, ZERO)
    tax_std = money(at_std * std_rate)
    tax_high = money(at_high * high_rate)
    ctx.add(C, "Standard-rate portion", f"{label}: pay up to the standard rate cut-off point",
            f"min({fmt(pay)}, {fmt(srcop)}) = {fmt(at_std)} × {pct(std_rate)}", tax_std,
            {"taxable_at_standard_rate": at_std}, pct(std_rate), std_rule)
    ctx.add(C, "Higher-rate portion", f"{label}: pay above the standard rate cut-off point",
            f"max({fmt(pay)} − {fmt(srcop)}, 0) = {fmt(at_high)} × {pct(high_rate)}", tax_high,
            {"taxable_at_higher_rate": at_high}, pct(high_rate), high_rule)
    gross = tax_std + tax_high
    ctx.add(C, "Gross tax", f"{label}: gross income tax", f"{fmt(tax_std)} + {fmt(tax_high)}", gross)
    net = max(gross - credits, ZERO)
    ctx.add(C, "Tax credits", f"{label}: tax credits applied (tax cannot go below zero)",
            f"max({fmt(gross)} − {fmt(credits)}, 0)", net, {"tax_credits": credits})
    return gross, net


def calculate_paye(ctx: CalcContext, pay_for_tax: Decimal) -> PayeOutcome:
    inp = ctx.inp
    prof = inp.tax_profile
    basis = prof.tax_basis
    n = inp.period_number

    # --- choose the basis, never guess -------------------------------------------------
    if not prof.rpn_present:
        basis = TaxBasis.EMERGENCY
        reason = ("No RPN is available for this employment, so the emergency basis is mandatory. "
                  + ("A PPSN is held, so the emergency cut-off applies for the initial period(s)."
                     if prof.ppsn_present else "No PPSN is held, so all pay is taxed at the higher rate with no credits."))
        ctx.add(C, "Basis selection", "Why the emergency basis was selected", reason, "EMERGENCY")
    elif basis is None:
        raise CalculationBlocked("TAX_BASIS_MISSING", "Unable to calculate reliably because the RPN tax basis is missing.")
    elif basis == TaxBasis.EMERGENCY:
        ctx.add(C, "Basis selection", "RPN instructs the emergency basis",
                "Revenue issued the RPN on the emergency basis.", "EMERGENCY")
    else:
        ctx.add(C, "Basis selection", "Basis taken from the RPN", f"RPN tax basis = {basis.value}", basis.value)

    if basis != TaxBasis.EMERGENCY and (prof.annual_srcop is None or prof.annual_tax_credits is None):
        raise CalculationBlocked("RPN_INCOMPLETE",
                                 "Unable to calculate reliably because the RPN tax credits / cut-off point are missing.")

    # --- emergency ---------------------------------------------------------------------
    if basis == TaxBasis.EMERGENCY:
        k = inp.ytd.emergency_periods + 1
        if not prof.ppsn_present:
            srcop = ZERO
            ctx.add(C, "Emergency cut-off", "No PPSN: no standard rate cut-off, no credits",
                    "cut-off = €0.00", ZERO, {"emergency_period_index": k})
        elif inp.frequency == PayFrequency.WEEKLY:
            r_amt = ctx.rule("EMERGENCY", "srcop_weekly_weeks_1_4")
            r_cnt = ctx.rule("EMERGENCY", "srcop_weekly_weeks_count")
            srcop = D(r_amt.value) if k <= int(r_cnt.value) else ZERO
            ctx.add(C, "Emergency cut-off", f"PPSN held, emergency week {k}",
                    f"week {k} {'≤' if k <= int(r_cnt.value) else '>'} {r_cnt.value} → cut-off {fmt(srcop)}",
                    srcop, {"emergency_period_index": k}, rule=r_amt)
        elif inp.frequency == PayFrequency.MONTHLY:
            r_amt = ctx.rule("EMERGENCY", "srcop_monthly_month_1")
            srcop = D(r_amt.value) if k == 1 else ZERO
            ctx.add(C, "Emergency cut-off", f"PPSN held, emergency month {k}",
                    f"month {k} → cut-off {fmt(srcop)}", srcop, {"emergency_period_index": k}, rule=r_amt)
        else:
            raise CalculationBlocked(
                "EMERGENCY_FREQ_UNVERIFIED",
                "Emergency basis for fortnightly pay has not been verified against Revenue tables; cannot calculate.",
                CalcStatus.UNVERIFIED,
            )
        credit_rule = ctx.rule("EMERGENCY", "tax_credits")
        credits = D(credit_rule.value)
        gross, net = _tax_on(ctx, pay_for_tax, srcop, credits, "Emergency (non-cumulative)")
        ctx.add(C, "PAYE due", "Emergency PAYE for this period", f"{fmt(net)}", net, rule=credit_rule)
        return PayeOutcome(net, gross, credits, basis, k)

    assert prof.annual_srcop is not None and prof.annual_tax_credits is not None
    period_srcop = ctx.periodise(prof.annual_srcop)
    period_credit = ctx.periodise(prof.annual_tax_credits)
    ctx.add(C, "Periodise RPN", f"Annual RPN figures → per {inp.frequency.value.lower()} period (rounded up to the cent)",
            f"cut-off {fmt(prof.annual_srcop)} ÷ {ctx.ppy} = {fmt(period_srcop)}; "
            f"credits {fmt(prof.annual_tax_credits)} ÷ {ctx.ppy} = {fmt(period_credit)}",
            period_srcop, {"period_credit": period_credit}, rule=ctx.rule("PAYE", "period_amount_rounding"))

    # --- Week 1 / Month 1 --------------------------------------------------------------
    if basis == TaxBasis.WEEK1_MONTH1:
        gross, net = _tax_on(ctx, pay_for_tax, period_srcop, period_credit, "Week 1/Month 1 (non-cumulative)")
        ctx.add(C, "PAYE due", "Non-cumulative PAYE for this period", f"{fmt(net)}", net)
        return PayeOutcome(net, gross, period_credit, basis)

    # --- Cumulative --------------------------------------------------------------------
    cum_srcop = period_srcop * n
    cum_credit = period_credit * n
    cum_pay = prof.prior_pay_for_tax + inp.ytd.pay_for_tax + pay_for_tax
    ctx.add(C, "Cumulative pay", "Previous YTD pay + this period",
            f"prior employment {fmt(prof.prior_pay_for_tax)} + this employment YTD {fmt(inp.ytd.pay_for_tax)} "
            f"+ this period {fmt(pay_for_tax)}", cum_pay)
    ctx.add(C, "Cumulative allowances", f"Cut-off and credits to period {n}",
            f"cut-off {fmt(period_srcop)} × {n} = {fmt(cum_srcop)}; credits {fmt(period_credit)} × {n} = {fmt(cum_credit)}",
            cum_srcop, {"cumulative_credits": cum_credit})
    gross, cum_net = _tax_on(ctx, cum_pay, cum_srcop, cum_credit, "Cumulative")
    already = prof.prior_tax + inp.ytd.tax
    due = cum_net - already
    ctx.add(C, "PAYE due", "New cumulative liability − tax already deducted (negative = refund)",
            f"{fmt(cum_net)} − ({fmt(prof.prior_tax)} + {fmt(inp.ytd.tax)})", due)
    if due < 0:
        ctx.warn("PAYE_REFUND", f"PAYE refund of {fmt(-due)} arises on the cumulative basis.", "INFO")
    # report period-level gross tax & credits for the payslip
    return PayeOutcome(due, gross, cum_credit, basis)
