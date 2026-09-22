"""Gross-to-net orchestrator.

Employee:   Gross − PAYE − USC − Employee PRSI − LPT − Employee pension − other deductions = Net
Employer:   Gross + Employer PRSI + Employer pension + BIK (benefits cost) = Total employer cost
Statutory:  PAYE + USC + Employee PRSI + Employer PRSI + LPT = Liability to Revenue
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.engine.components import calculate_bik, calculate_lpt, calculate_pension
from app.engine.context import CalcContext
from app.engine.money import ZERO, fmt, money
from app.engine.paye import calculate_paye
from app.engine.prsi import calculate_prsi
from app.engine.types import (
    CalcStatus,
    CalculationBlocked,
    PayrollInput,
    PayrollResult,
    TaxBasis,
)
from app.engine.usc import calculate_usc
from app.rules.repository import RuleRepository, default_repository


class PayrollEngine:
    def __init__(self, repo: RuleRepository | None = None):
        self.repo = repo or default_repository()

    def calculate(self, inp: PayrollInput) -> PayrollResult:
        ctx = CalcContext(self.repo, inp)
        try:
            return self._calculate(ctx)
        except CalculationBlocked as exc:
            return PayrollResult(
                employee_ref=inp.employee_ref,
                status=exc.status,
                error_code=exc.code,
                error_message=exc.message,
                trace=ctx.trace,
                messages=ctx.messages + [{"code": exc.code, "severity": "CRITICAL", "message": exc.message}],
                rules_used=ctx.rules_used,
            )

    # ------------------------------------------------------------------
    def _validate_input(self, inp: PayrollInput) -> None:
        if inp.payment_date.year != inp.tax_year:
            raise CalculationBlocked("TAX_YEAR_MISMATCH",
                                     f"Payment date {inp.payment_date} is not in tax year {inp.tax_year}.", CalcStatus.INVALID)
        if not 1 <= inp.period_number <= inp.frequency.periods_per_year + 1:
            raise CalculationBlocked("PERIOD_INVALID", f"Period {inp.period_number} is invalid for {inp.frequency.value}.",
                                     CalcStatus.INVALID)
        for e in inp.earnings:
            if e.amount < 0 and e.type.value not in {"ADJUSTMENT", "ARREARS", "BACK_PAY"}:
                raise CalculationBlocked("NEGATIVE_EARNING", f"Negative {e.type.value} earning is not allowed.",
                                         CalcStatus.INVALID)
        for d in inp.deductions:
            if d.amount < 0:
                raise CalculationBlocked("NEGATIVE_DEDUCTION", f"Deduction {d.code} is negative.", CalcStatus.INVALID)

    def _calculate(self, ctx: CalcContext) -> PayrollResult:
        inp = ctx.inp
        self._validate_input(inp)

        # 1. Earnings ---------------------------------------------------
        gross = money(sum((e.amount for e in inp.earnings), ZERO))
        earnings = [{"type": e.type.value, "description": e.description or e.type.value.title().replace("_", " "),
                     "amount": money(e.amount)} for e in inp.earnings]
        ctx.add("GROSS", "Gross pay", "Sum of cash earnings",
                " + ".join(f"{x['description']} {fmt(x['amount'])}" for x in earnings) or "no earnings", gross)
        if gross < 0:
            raise CalculationBlocked("NEGATIVE_GROSS", f"Gross pay is negative ({fmt(gross)}).", CalcStatus.INVALID)

        # 2. BIK (notional pay) -----------------------------------------
        bik, sb_count, sb_value = calculate_bik(ctx)
        if bik:
            ctx.add("BIK", "Notional pay", "Total taxable benefit added to pay for PAYE, USC and PRSI", fmt(bik), bik,
                    rule=ctx.rule("BIK", "notional_pay_treatment"))

        # 3. Pension ----------------------------------------------------
        pension_ee, pension_er, relieved = calculate_pension(ctx, gross)

        # 4. Pay bases --------------------------------------------------
        pay_for_tax = gross + bik - relieved
        pay_for_usc = gross + bik
        pay_for_prsi = gross + bik
        ctx.add("GROSS", "Pay for tax", "Gross + BIK − pension relieved under net pay arrangement",
                f"{fmt(gross)} + {fmt(bik)} − {fmt(relieved)}", pay_for_tax)
        ctx.add("GROSS", "Pay for USC", "Gross + BIK (pension NOT deducted)", f"{fmt(gross)} + {fmt(bik)}", pay_for_usc)
        ctx.add("GROSS", "Pay for PRSI", "Gross + BIK (pension NOT deducted)", f"{fmt(gross)} + {fmt(bik)}", pay_for_prsi)

        # 5. Statutory deductions ---------------------------------------
        paye = calculate_paye(ctx, pay_for_tax)
        usc, usc_status = calculate_usc(ctx, pay_for_usc, paye.basis)
        prsi = calculate_prsi(ctx, pay_for_prsi)
        lpt = calculate_lpt(ctx)
        other = money(sum((d.amount for d in inp.deductions), ZERO))

        # 6. Net ------------------------------------------------------
        net = gross - paye.paye - usc - prsi.employee - lpt - pension_ee - other
        ctx.add("NET", "Net pay", "Gross − PAYE − USC − employee PRSI − LPT − employee pension − other deductions",
                f"{fmt(gross)} − {fmt(paye.paye)} − {fmt(usc)} − {fmt(prsi.employee)} − {fmt(lpt)} − "
                f"{fmt(pension_ee)} − {fmt(other)}", net)
        employer_cost = gross + prsi.employer + pension_er + bik
        ctx.add("EMPLOYER", "Employer cost", "Gross + employer PRSI + employer pension + benefits (BIK value)",
                f"{fmt(gross)} + {fmt(prsi.employer)} + {fmt(pension_er)} + {fmt(bik)}", employer_cost)
        liability = paye.paye + usc + prsi.employee + prsi.employer + lpt
        ctx.add("LIABILITY", "Statutory liability", "PAYE + USC + employee PRSI + employer PRSI + LPT",
                f"{fmt(paye.paye)} + {fmt(usc)} + {fmt(prsi.employee)} + {fmt(prsi.employer)} + {fmt(lpt)}", liability)

        if net < 0:
            ctx.warn("NEGATIVE_NET", f"Net pay is negative ({fmt(net)}).", "ERROR")

        deductions = [
            {"code": "PAYE", "description": "PAYE income tax", "amount": paye.paye},
            {"code": "USC", "description": "Universal Social Charge", "amount": usc},
            {"code": "PRSI_EE", "description": f"PRSI (Class {prsi.subclass})", "amount": prsi.employee},
        ]
        if lpt:
            deductions.append({"code": "LPT", "description": "Local Property Tax", "amount": lpt})
        if pension_ee:
            deductions.append({"code": "PENSION_EE", "description": "Employee pension", "amount": pension_ee})
        for d in inp.deductions:
            deductions.append({"code": d.code, "description": d.description or d.code, "amount": money(d.amount)})

        y = inp.ytd
        new_ytd = replace(
            y,
            gross=y.gross + gross,
            pay_for_tax=y.pay_for_tax + pay_for_tax,
            tax=y.tax + paye.paye,
            usc_pay=y.usc_pay + pay_for_usc,
            usc=y.usc + usc,
            prsi_pay=y.prsi_pay + pay_for_prsi,
            prsi_ee=y.prsi_ee + prsi.employee,
            prsi_er=y.prsi_er + prsi.employer,
            lpt=y.lpt + lpt,
            pension_ee=y.pension_ee + pension_ee,
            pension_relieved=y.pension_relieved + relieved,
            pension_er=y.pension_er + pension_er,
            bik=y.bik + bik,
            net=y.net + net,
            small_benefit_count=y.small_benefit_count + sb_count,
            small_benefit_value=y.small_benefit_value + sb_value,
            emergency_periods=paye.emergency_period_index if paye.basis == TaxBasis.EMERGENCY else y.emergency_periods,
        )

        return PayrollResult(
            employee_ref=inp.employee_ref,
            status=CalcStatus.CALCULATED,
            gross_pay=gross,
            bik=bik,
            pay_for_tax=money(pay_for_tax),
            pay_for_usc=money(pay_for_usc),
            pay_for_prsi=money(pay_for_prsi),
            gross_tax=money(paye.gross_tax),
            tax_credits=money(paye.credits),
            paye=money(paye.paye),
            usc=money(usc),
            prsi_ee=money(prsi.employee),
            prsi_er=money(prsi.employer),
            prsi_class=prsi.prsi_class,
            prsi_subclass=prsi.subclass,
            insurable_weeks=prsi.insurable_weeks,
            lpt=money(lpt),
            pension_ee=money(pension_ee),
            pension_er=money(pension_er),
            other_deductions=other,
            net_pay=money(net),
            employer_cost=money(employer_cost),
            statutory_liability=money(liability),
            tax_basis_applied=paye.basis.value,
            usc_status_applied=usc_status,
            earnings=earnings,
            deductions=[{**d, "amount": money(d["amount"])} for d in deductions],
            new_ytd=new_ytd,
            trace=ctx.trace,
            messages=ctx.messages,
            rules_used=ctx.rules_used,
        )


def explain(result: PayrollResult, component: str) -> list[dict]:
    """'Why was this employee's PAYE €x?' - the trace steps for one component."""
    return [t.to_dict() for t in result.trace if t.component == component.upper()]


__all__ = ["PayrollEngine", "explain", "Decimal"]
