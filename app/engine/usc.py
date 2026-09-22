"""USC engine - independent of PAYE. Band-by-band trace, cumulative or non-cumulative."""

from __future__ import annotations

from decimal import Decimal

from app.engine.context import CalcContext
from app.engine.money import ZERO, D, fmt, money, pct
from app.engine.types import CalculationBlocked, TaxBasis, UscStatus

C = "USC"


def _bands(ctx: CalcContext, reduced: bool) -> tuple[list[tuple[Decimal | None, Decimal]], object]:
    rule = ctx.rule(C, "reduced_bands" if reduced else "standard_bands")
    bands = [(D(b["upper"]) if b["upper"] is not None else None, D(b["rate"])) for b in rule.value]
    return bands, rule


def _apply(ctx: CalcContext, pay: Decimal, bands, rule, multiplier: int, label: str) -> Decimal:
    """Apply annual bands scaled to `multiplier` periods (cut-offs periodised, then × periods)."""
    total = ZERO
    lower = ZERO
    for i, (upper_annual, rate) in enumerate(bands, start=1):
        if upper_annual is None:
            upper = None
        else:
            upper = ctx.periodise(upper_annual) * multiplier
        top = pay if upper is None else min(pay, upper)
        slice_ = max(top - lower, ZERO)
        amt = money(slice_ * rate)
        total += amt
        band_desc = f"{fmt(lower)} – {'∞' if upper is None else fmt(upper)}"
        ctx.add(C, f"Band {i}", f"{label}: USC band {i} ({band_desc})",
                f"{fmt(slice_)} × {pct(rate)}", amt, {"band_from": lower, "band_to": upper or "open"},
                pct(rate), rule)  # type: ignore[arg-type]
        if upper is None or pay <= upper:
            # remaining bands contribute nothing, still show them for transparency
            lower = upper if upper is not None else lower
            for j, (_u2, r2) in enumerate(bands[i:], start=i + 1):
                ctx.add(C, f"Band {j}", f"{label}: USC band {j}", f"€0.00 × {pct(r2)}", ZERO, rate=pct(r2))
            break
        lower = upper
    ctx.add(C, "Total USC", f"{label}: total", "sum of bands", total)
    return total


def calculate_usc(ctx: CalcContext, usc_pay: Decimal, paye_basis: TaxBasis) -> tuple[Decimal, str]:
    inp = ctx.inp
    prof = inp.tax_profile

    if paye_basis == TaxBasis.EMERGENCY:
        r = ctx.rule("EMERGENCY", "usc_rate")
        amt = money(max(usc_pay, ZERO) * D(r.value))
        ctx.add(C, "Emergency USC", "Emergency basis: flat rate on all USC pay, no cut-offs",
                f"{fmt(usc_pay)} × {pct(r.value)}", amt, rate=pct(r.value), rule=r)
        return amt, "EMERGENCY"

    status = prof.usc_status
    if status is None:
        raise CalculationBlocked("USC_STATUS_MISSING", "Unable to calculate reliably because the RPN USC status is missing.")
    if status == UscStatus.EXEMPT:
        r = ctx.rule(C, "exemption_threshold")
        ctx.add(C, "Exempt", "RPN marks this employee USC-exempt",
                f"Revenue determined total income ≤ {fmt(r.value)}; no USC deducted", ZERO, rule=r)
        return ZERO, "EXEMPT"

    reduced = status == UscStatus.REDUCED
    bands, rule = _bands(ctx, reduced)
    if reduced:
        ctx.add(C, "Reduced rate", "RPN USC status is REDUCED (age 70+ or full medical card, income ≤ €60,000)",
                "reduced bands applied", "REDUCED", rule=rule)  # type: ignore[arg-type]

    if paye_basis == TaxBasis.WEEK1_MONTH1:
        amt = _apply(ctx, usc_pay, bands, rule, 1, "Non-cumulative")
        return amt, status.value

    n = inp.period_number
    cum_pay = prof.prior_usc_pay + inp.ytd.usc_pay + usc_pay
    ctx.add(C, "Cumulative USC pay", "Previous YTD USC pay + this period",
            f"{fmt(prof.prior_usc_pay)} + {fmt(inp.ytd.usc_pay)} + {fmt(usc_pay)}", cum_pay)
    cum = _apply(ctx, cum_pay, bands, rule, n, f"Cumulative to period {n}")
    already = prof.prior_usc + inp.ytd.usc
    due = cum - already
    ctx.add(C, "USC due", "Cumulative USC − USC already deducted",
            f"{fmt(cum)} − {fmt(already)}", due)
    return due, status.value
