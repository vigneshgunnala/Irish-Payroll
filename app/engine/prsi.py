"""PRSI engine - class/subclass framework, always calculated per pay period (non-cumulative).

Weekly thresholds from the DSP tables are converted to the pay period using the verified
weeks-per-period factor (1 / 2 / 52÷12). Rates are selected by payment date, so the
1 October 2026 increase applies automatically to pay dates from that day.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.engine.context import CalcContext
from app.engine.money import ZERO, D, fmt, money, pct
from app.engine.types import CalculationBlocked, PayFrequency

C = "PRSI"
SUPPORTED = {"A", "B", "C", "D", "H", "J", "K", "M", "S"}


@dataclass
class PrsiOutcome:
    prsi_class: str
    subclass: str
    employee: Decimal
    employer: Decimal
    credit: Decimal
    insurable_weeks: int


def _wpp(ctx: CalcContext) -> Decimal:
    r = ctx.rule(C, "weeks_per_period")
    return D(r.value[ctx.inp.frequency.value])


def _thr(weekly: str | Decimal, wpp: Decimal) -> Decimal:
    return money(D(weekly) * wpp)


def _subclass(value: dict, pay: Decimal, wpp: Decimal) -> str:
    for sc in value["subclasses"]:
        if sc["upper_weekly"] is None or pay <= _thr(sc["upper_weekly"], wpp):
            return sc["code"]
    return value["subclasses"][-1]["code"]


def _credit(ctx: CalcContext, v: dict, pay: Decimal, wpp: Decimal, rule) -> Decimal:
    lower = _thr(v["credit_lower_weekly"], wpp)
    upper = _thr(v["credit_upper_weekly"], wpp)
    max_credit = _thr(v["credit_max_weekly"], wpp)
    if pay < lower or pay > upper:
        ctx.add(C, "PRSI credit", "Earnings outside the tapered credit band",
                f"{fmt(pay)} not in {fmt(lower)}–{fmt(upper)}", ZERO, rule=rule)
        return ZERO
    reduction = money((pay - lower) / D(v["credit_taper_divisor"]))
    credit = max(max_credit - reduction, ZERO)
    ctx.add(C, "PRSI credit", "Tapered credit: max credit − 1/6 of earnings above the lower limit",
            f"{fmt(max_credit)} − ({fmt(pay)} − {fmt(lower)}) ÷ {v['credit_taper_divisor']} "
            f"= {fmt(max_credit)} − {fmt(reduction)}", credit, rule=rule)
    return credit


def calculate_prsi(ctx: CalcContext, prsi_pay: Decimal) -> PrsiOutcome:
    inp = ctx.inp
    klass = (inp.prsi_class or "").strip().upper()[:1]
    if not klass:
        raise CalculationBlocked("PRSI_CLASS_MISSING", "PRSI classification cannot be confirmed: no PRSI class held.")
    if klass not in SUPPORTED:
        raise CalculationBlocked("PRSI_CLASS_INVALID", f"PRSI class '{inp.prsi_class}' is not supported by this engine.")

    wpp = _wpp(ctx)
    weeks = inp.insurable_weeks or {PayFrequency.WEEKLY: 1, PayFrequency.FORTNIGHTLY: 2, PayFrequency.MONTHLY: 4}[inp.frequency]
    pay = max(prsi_pay, ZERO)
    ctx.add(C, "Reckonable pay", "Pay for PRSI (includes BIK; employee pension NOT deducted)",
            f"{fmt(pay)} for a {inp.frequency.value.lower()} period ({wpp.normalize()} weeks)", pay,
            {"weeks_per_period": wpp, "insurable_weeks": weeks}, rule=ctx.rule(C, "weeks_per_period"))

    # Class A below €38/week drops to Class J (J0)
    if klass == "A":
        rule = ctx.rule(C, "class_A")
        v = rule.value
        if pay < _thr(v["class_j_below_weekly"], wpp):
            ctx.add(C, "Class", "Earnings below the Class A floor are insurable at Class J",
                    f"{fmt(pay)} < {fmt(_thr(v['class_j_below_weekly'], wpp))}", "J0", rule=rule)
            klass = "J"

    rule = ctx.rule(C, f"class_{klass}")
    v = rule.value
    subclass = _subclass(v, pay, wpp)
    ctx.add(C, "Subclass", f"Class {klass} subclass from weekly-equivalent earnings", f"→ {subclass}", subclass, rule=rule)
    credit = ZERO

    if klass == "A":
        exempt = _thr(v["employee_exempt_up_to_weekly"], wpp)
        if pay <= exempt:
            ee = ZERO
            ctx.add(C, "Employee PRSI", "At or below the employee threshold: no employee PRSI",
                    f"{fmt(pay)} ≤ {fmt(exempt)}", ZERO, rate="0%", rule=rule)
        else:
            gross_ee = money(pay * D(v["employee_rate"]))
            ctx.add(C, "Employee PRSI (before credit)", "Employee rate on ALL reckonable pay",
                    f"{fmt(pay)} × {pct(v['employee_rate'])}", gross_ee, rate=pct(v["employee_rate"]), rule=rule)
            credit = _credit(ctx, v, pay, wpp, rule)
            ee = max(gross_ee - credit, ZERO)
            ctx.add(C, "Employee PRSI", "Employee PRSI after credit", f"{fmt(gross_ee)} − {fmt(credit)}", ee, rule=rule)
        lower_thr = _thr(v["employer_lower_up_to_weekly"], wpp)
        er_rate = D(v["employer_lower_rate"]) if pay <= lower_thr else D(v["employer_higher_rate"])
        er = money(pay * er_rate)
        ctx.add(C, "Employer PRSI", "Employer rate on ALL reckonable pay (lower rate if within the employer threshold)",
                f"{fmt(pay)} {'≤' if pay <= lower_thr else '>'} {fmt(lower_thr)} → {fmt(pay)} × {pct(er_rate)}",
                er, rate=pct(er_rate), rule=rule)

    elif klass == "H":
        exempt = _thr(v["employee_exempt_up_to_weekly"], wpp)
        if pay <= exempt:
            ee = ZERO
        else:
            gross_ee = money(pay * D(v["employee_rate"]))
            credit = _credit(ctx, v, pay, wpp, rule)
            ee = max(gross_ee - credit, ZERO)
        ctx.add(C, "Employee PRSI", "Class H employee PRSI", f"rate {pct(v['employee_rate'])} less credit", ee, rule=rule)
        er = money(pay * D(v["employer_rate"]))
        ctx.add(C, "Employer PRSI", "Class H employer PRSI", f"{fmt(pay)} × {pct(v['employer_rate'])}", er, rule=rule)

    elif klass in {"B", "C", "D"}:
        exempt = _thr(v["employee_exempt_up_to_weekly"], wpp)
        if pay <= exempt:
            ee = ZERO
            ctx.add(C, "Employee PRSI", f"Class {klass}: at or below threshold", f"{fmt(pay)} ≤ {fmt(exempt)}", ZERO, rule=rule)
        else:
            band = _thr(v["employee_lower_up_to_weekly"], wpp)
            low = money(min(pay, band) * D(v["employee_lower_rate"]))
            high = money(max(pay - band, ZERO) * D(v["employee_higher_rate"]))
            ee = low + high
            ctx.add(C, "Employee PRSI", f"Class {klass}: lower rate up to {fmt(band)}, higher rate on balance",
                    f"{fmt(min(pay, band))} × {pct(v['employee_lower_rate'])} + {fmt(max(pay - band, ZERO))} × "
                    f"{pct(v['employee_higher_rate'])}", ee, rule=rule)
        er = money(pay * D(v["employer_rate"]))
        ctx.add(C, "Employer PRSI", f"Class {klass} employer PRSI", f"{fmt(pay)} × {pct(v['employer_rate'])}", er, rule=rule)

    elif klass == "K":
        exempt = _thr(v["employee_exempt_up_to_weekly"], wpp)
        ee = ZERO if pay <= exempt else money(pay * D(v["employee_rate"]))
        er = ZERO
        ctx.add(C, "Employee PRSI", "Class K (no employer share)",
                f"{fmt(pay)} × {pct(v['employee_rate'])} if > {fmt(exempt)}", ee, rule=rule)

    else:  # J, M, S - flat
        ee = money(pay * D(v["employee_rate"]))
        er = money(pay * D(v["employer_rate"]))
        ctx.add(C, "Employee PRSI", f"Class {klass} employee PRSI", f"{fmt(pay)} × {pct(v['employee_rate'])}", ee, rule=rule)
        ctx.add(C, "Employer PRSI", f"Class {klass} employer PRSI", f"{fmt(pay)} × {pct(v['employer_rate'])}", er, rule=rule)

    return PrsiOutcome(klass, subclass, ee, er, credit, weeks)
