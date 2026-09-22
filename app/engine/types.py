"""Engine input/output types. Pure dataclasses - no database, no UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from app.engine.money import ZERO


class PayFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    FORTNIGHTLY = "FORTNIGHTLY"
    MONTHLY = "MONTHLY"

    @property
    def periods_per_year(self) -> int:
        return {"WEEKLY": 52, "FORTNIGHTLY": 26, "MONTHLY": 12}[self.value]


class TaxBasis(str, Enum):
    CUMULATIVE = "CUMULATIVE"
    WEEK1_MONTH1 = "WEEK1_MONTH1"  # non-cumulative
    EMERGENCY = "EMERGENCY"


class UscStatus(str, Enum):
    ORDINARY = "ORDINARY"
    REDUCED = "REDUCED"
    EXEMPT = "EXEMPT"


class PensionScheme(str, Enum):
    OCCUPATIONAL = "OCCUPATIONAL"
    AVC = "AVC"
    PRSA = "PRSA"
    RAC = "RAC"


class EarningType(str, Enum):
    BASIC = "BASIC"
    HOURLY = "HOURLY"
    OVERTIME = "OVERTIME"
    BONUS = "BONUS"
    COMMISSION = "COMMISSION"
    HOLIDAY_PAY = "HOLIDAY_PAY"
    ALLOWANCE = "ALLOWANCE"
    SHIFT_PREMIUM = "SHIFT_PREMIUM"
    ARREARS = "ARREARS"
    BACK_PAY = "BACK_PAY"
    OTHER_TAXABLE = "OTHER_TAXABLE"
    ADJUSTMENT = "ADJUSTMENT"  # may be negative


class BenefitType(str, Enum):
    COMPANY_CAR = "COMPANY_CAR"
    MEDICAL_INSURANCE = "MEDICAL_INSURANCE"
    SMALL_BENEFIT = "SMALL_BENEFIT"
    OTHER = "OTHER"  # accommodation, preferential loan etc. - valued outside and entered as cash equivalent


class CalcStatus(str, Enum):
    CALCULATED = "CALCULATED"
    MISSING = "MISSING"
    INVALID = "INVALID"
    UNVERIFIED = "UNVERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class EarningLine:
    type: EarningType
    amount: Decimal
    description: str = ""
    hours: Decimal | None = None
    rate: Decimal | None = None


@dataclass
class BenefitLine:
    type: BenefitType
    description: str = ""
    # company car
    omv: Decimal | None = None
    co2_g_km: Decimal | None = None
    business_km: int | None = None
    employee_contribution_annual: Decimal = ZERO
    # medical insurance / other
    annual_value: Decimal | None = None
    period_value: Decimal | None = None
    # small benefit
    value: Decimal | None = None


@dataclass
class PensionContribution:
    scheme: PensionScheme
    employee_amount: Decimal = ZERO
    employer_amount: Decimal = ZERO


@dataclass
class Deduction:
    code: str
    amount: Decimal
    description: str = ""


@dataclass
class TaxProfile:
    """What Revenue told us (via the RPN) plus identity facts that drive emergency tax."""

    tax_basis: TaxBasis | None
    annual_tax_credits: Decimal | None
    annual_srcop: Decimal | None
    usc_status: UscStatus | None
    ppsn_present: bool
    rpn_present: bool
    rpn_number: str | None = None
    usc_annual_cutoffs: list[Decimal] | None = None  # optional RPN-supplied cut-offs
    lpt_annual: Decimal = ZERO
    # previous-employment figures in this tax year (RPN pay/tax to date)
    prior_pay_for_tax: Decimal = ZERO
    prior_tax: Decimal = ZERO
    prior_usc_pay: Decimal = ZERO
    prior_usc: Decimal = ZERO


@dataclass
class YearToDate:
    """Figures already processed in THIS employment in THIS tax year (before this period)."""

    gross: Decimal = ZERO
    pay_for_tax: Decimal = ZERO
    tax: Decimal = ZERO
    usc_pay: Decimal = ZERO
    usc: Decimal = ZERO
    prsi_pay: Decimal = ZERO
    prsi_ee: Decimal = ZERO
    prsi_er: Decimal = ZERO
    lpt: Decimal = ZERO
    pension_ee: Decimal = ZERO
    pension_relieved: Decimal = ZERO
    pension_er: Decimal = ZERO
    bik: Decimal = ZERO
    net: Decimal = ZERO
    small_benefit_count: int = 0
    small_benefit_value: Decimal = ZERO
    emergency_periods: int = 0  # emergency periods already processed in this employment


@dataclass
class PayrollInput:
    employee_ref: str
    tax_year: int
    frequency: PayFrequency
    period_number: int
    payment_date: date
    prsi_class: str | None
    tax_profile: TaxProfile
    ytd: YearToDate = field(default_factory=YearToDate)
    earnings: list[EarningLine] = field(default_factory=list)
    benefits: list[BenefitLine] = field(default_factory=list)
    pensions: list[PensionContribution] = field(default_factory=list)
    deductions: list[Deduction] = field(default_factory=list)
    date_of_birth: date | None = None
    insurable_weeks: int | None = None


@dataclass
class TraceStep:
    component: str
    step: str
    description: str
    calculation: str
    result: Decimal | str | None
    inputs: dict[str, Any] = field(default_factory=dict)
    rate: str | None = None
    rule: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if isinstance(self.result, Decimal):
            d["result"] = str(self.result)
        d["inputs"] = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.inputs.items()}
        return d


@dataclass
class ComponentResult:
    amount: Decimal
    status: CalcStatus = CalcStatus.CALCULATED
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PayrollResult:
    employee_ref: str
    status: CalcStatus
    gross_pay: Decimal = ZERO
    bik: Decimal = ZERO
    pay_for_tax: Decimal = ZERO
    pay_for_usc: Decimal = ZERO
    pay_for_prsi: Decimal = ZERO
    gross_tax: Decimal = ZERO
    tax_credits: Decimal = ZERO
    paye: Decimal = ZERO
    usc: Decimal = ZERO
    prsi_ee: Decimal = ZERO
    prsi_er: Decimal = ZERO
    prsi_class: str | None = None
    prsi_subclass: str | None = None
    insurable_weeks: int = 0
    lpt: Decimal = ZERO
    pension_ee: Decimal = ZERO
    pension_er: Decimal = ZERO
    other_deductions: Decimal = ZERO
    net_pay: Decimal = ZERO
    employer_cost: Decimal = ZERO
    statutory_liability: Decimal = ZERO
    tax_basis_applied: str | None = None
    usc_status_applied: str | None = None
    earnings: list[dict[str, Any]] = field(default_factory=list)
    deductions: list[dict[str, Any]] = field(default_factory=list)
    new_ytd: YearToDate | None = None
    trace: list[TraceStep] = field(default_factory=list)
    messages: list[dict[str, str]] = field(default_factory=list)
    rules_used: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None

    MONEY_FIELDS = (
        "gross_pay", "bik", "pay_for_tax", "pay_for_usc", "pay_for_prsi", "gross_tax", "tax_credits",
        "paye", "usc", "prsi_ee", "prsi_er", "lpt", "pension_ee", "pension_er", "other_deductions",
        "net_pay", "employer_cost", "statutory_liability",
    )

    def summary(self) -> dict[str, Any]:
        d: dict[str, Any] = {k: getattr(self, k) for k in self.MONEY_FIELDS}
        d.update(
            employee_ref=self.employee_ref,
            status=self.status.value,
            prsi_class=self.prsi_class,
            prsi_subclass=self.prsi_subclass,
            insurable_weeks=self.insurable_weeks,
            tax_basis_applied=self.tax_basis_applied,
            usc_status_applied=self.usc_status_applied,
            error_code=self.error_code,
            error_message=self.error_message,
        )
        return d

    def trace_dicts(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.trace]


class CalculationBlocked(Exception):
    """Raised when the engine refuses to produce a figure it cannot stand behind."""

    def __init__(self, code: str, message: str, status: CalcStatus = CalcStatus.MISSING):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
