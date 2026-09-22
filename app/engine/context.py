"""Calculation context shared by the component engines of one employee calculation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.engine.money import ceil_cent, money
from app.engine.types import CalcStatus, CalculationBlocked, PayrollInput, TraceStep
from app.rules.repository import Rule, RuleError, RuleRepository, UnverifiedRuleError


@dataclass
class CalcContext:
    repo: RuleRepository
    inp: PayrollInput
    trace: list[TraceStep] = field(default_factory=list)
    rules_used: list[str] = field(default_factory=list)
    messages: list[dict[str, str]] = field(default_factory=list)

    @property
    def on(self):  # the date that selects the rule version (Revenue: pay date drives the tax year)
        return self.inp.payment_date

    @property
    def ppy(self) -> int:
        return self.inp.frequency.periods_per_year

    def rule(self, category: str, parameter: str) -> Rule:
        try:
            r = self.repo.get(category, parameter, self.on)
        except UnverifiedRuleError as exc:
            raise CalculationBlocked(exc.code, str(exc), CalcStatus.UNVERIFIED) from exc
        except RuleError as exc:
            raise CalculationBlocked(exc.code, str(exc), CalcStatus.MISSING) from exc
        if r.rule_id not in self.rules_used:
            self.rules_used.append(r.rule_id)
        return r

    def periodise(self, annual: Decimal) -> Decimal:
        """Annual figure -> per-period figure using Revenue's round-up-to-the-cent convention."""
        rounding = self.rule("PAYE", "period_amount_rounding").value
        if rounding != "ROUND_UP_CENT":
            raise CalculationBlocked("RULE_INVALID", f"Unsupported period rounding '{rounding}'", CalcStatus.INVALID)
        return ceil_cent(Decimal(annual) / Decimal(self.ppy))

    def add(
        self,
        component: str,
        step: str,
        description: str,
        calculation: str,
        result: Any,
        inputs: dict[str, Any] | None = None,
        rate: str | None = None,
        rule: Rule | None = None,
    ) -> None:
        if isinstance(result, Decimal):
            result = money(result)
        self.trace.append(
            TraceStep(
                component=component,
                step=step,
                description=description,
                calculation=calculation,
                result=result,
                inputs=inputs or {},
                rate=rate,
                rule=rule.reference() if rule else None,
            )
        )

    def warn(self, code: str, message: str, severity: str = "WARNING") -> None:
        self.messages.append({"code": code, "severity": severity, "message": message})
