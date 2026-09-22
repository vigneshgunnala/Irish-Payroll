"""Relational data model (PostgreSQL-ready, also runs on SQLite for local demos/tests)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, Timestamped, utcnow

Money = Numeric(14, 2)


# ------------------------------------------------------------------ organisation


class Company(Timestamped, Base):
    __tablename__ = "companies"
    company_id: Mapped[int] = mapped_column(primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    trading_name: Mapped[str | None] = mapped_column(String(200))
    tax_registration_number: Mapped[str] = mapped_column(String(20), unique=True)  # employer registration no.
    employer_registration_details: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40))
    payroll_frequency: Mapped[str] = mapped_column(String(20), default="MONTHLY")
    financial_year: Mapped[int] = mapped_column(Integer, default=2026)

    departments: Mapped[list[Department]] = relationship(back_populates="company")
    employees: Mapped[list[Employee]] = relationship(back_populates="company")


class Department(Base):
    __tablename__ = "departments"
    department_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    cost_centre: Mapped[str | None] = mapped_column(String(20))
    monthly_budget: Mapped[Decimal | None] = mapped_column(Money)
    company: Mapped[Company] = relationship(back_populates="departments")
    __table_args__ = (UniqueConstraint("company_id", "name"),)


class RoleRecord(Base):
    __tablename__ = "roles"
    role_id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(200))
    permissions: Mapped[list[str]] = mapped_column(JSONType, default=list)


class User(Timestamped, Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(ForeignKey("roles.code"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ------------------------------------------------------------------ employees


class Employee(Timestamped, Base):
    __tablename__ = "employees"
    employee_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), index=True)
    employee_number: Mapped[str] = mapped_column(String(20))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    ppsn: Mapped[str | None] = mapped_column(String(10))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    employment_start_date: Mapped[date] = mapped_column(Date)
    employment_end_date: Mapped[date | None] = mapped_column(Date)
    employment_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.department_id"), index=True)
    job_title: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(120))
    contract_type: Mapped[str | None] = mapped_column(String(40))
    salary_type: Mapped[str] = mapped_column(String(10), default="SALARY")  # SALARY | HOURLY
    annual_salary: Mapped[Decimal | None] = mapped_column(Money)
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    standard_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    pay_frequency: Mapped[str] = mapped_column(String(20), default="MONTHLY")
    prsi_class: Mapped[str | None] = mapped_column(String(2))
    pension_scheme: Mapped[str | None] = mapped_column(String(20))
    pension_ee_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    pension_er_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    employment_id: Mapped[str | None] = mapped_column(String(20))  # Revenue employment identifier
    bank_iban_masked: Mapped[str | None] = mapped_column(String(40))  # placeholder only - no full IBAN in MVP

    company: Mapped[Company] = relationship(back_populates="employees")
    department: Mapped[Department | None] = relationship()
    tax_profile: Mapped[EmployeeTaxProfile | None] = relationship(back_populates="employee", uselist=False)
    benefits: Mapped[list[EmployeeBenefit]] = relationship(back_populates="employee")

    __table_args__ = (
        UniqueConstraint("company_id", "employee_number"),
        CheckConstraint("annual_salary IS NULL OR annual_salary >= 0", name="salary_non_negative"),
        CheckConstraint("hourly_rate IS NULL OR hourly_rate >= 0", name="rate_non_negative"),
        CheckConstraint("salary_type IN ('SALARY','HOURLY')", name="salary_type_valid"),
        CheckConstraint("pay_frequency IN ('WEEKLY','FORTNIGHTLY','MONTHLY')", name="freq_valid"),
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class EmployeeTaxProfile(Timestamped, Base):
    """Current RPN-derived tax position. Changes are audited; RPN history is in rpn_records."""

    __tablename__ = "employee_tax_profiles"
    profile_id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.employee_id", ondelete="CASCADE"), unique=True)
    tax_basis: Mapped[str | None] = mapped_column(String(20))
    annual_tax_credits: Mapped[Decimal | None] = mapped_column(Money)
    annual_srcop: Mapped[Decimal | None] = mapped_column(Money)
    usc_status: Mapped[str | None] = mapped_column(String(20))
    lpt_annual: Mapped[Decimal] = mapped_column(Money, default=0)
    prior_pay_for_tax: Mapped[Decimal] = mapped_column(Money, default=0)
    prior_tax: Mapped[Decimal] = mapped_column(Money, default=0)
    prior_usc_pay: Mapped[Decimal] = mapped_column(Money, default=0)
    prior_usc: Mapped[Decimal] = mapped_column(Money, default=0)
    rpn_number: Mapped[str | None] = mapped_column(String(30))
    rpn_effective_date: Mapped[date | None] = mapped_column(Date)
    rpn_source: Mapped[str | None] = mapped_column(String(40))
    rpn_imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    employee: Mapped[Employee] = relationship(back_populates="tax_profile")


class RpnRecord(Base):
    __tablename__ = "rpn_records"
    rpn_id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.employee_id", ondelete="CASCADE"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    rpn_number: Mapped[str] = mapped_column(String(30))
    employment_id: Mapped[str | None] = mapped_column(String(20))
    effective_date: Mapped[date] = mapped_column(Date)
    tax_basis: Mapped[str] = mapped_column(String(20))
    annual_tax_credits: Mapped[Decimal] = mapped_column(Money)
    annual_srcop: Mapped[Decimal] = mapped_column(Money)
    usc_status: Mapped[str] = mapped_column(String(20))
    lpt_annual: Mapped[Decimal] = mapped_column(Money, default=0)
    prior_pay_for_tax: Mapped[Decimal] = mapped_column(Money, default=0)
    prior_tax: Mapped[Decimal] = mapped_column(Money, default=0)
    prior_usc_pay: Mapped[Decimal] = mapped_column(Money, default=0)
    prior_usc: Mapped[Decimal] = mapped_column(Money, default=0)
    source: Mapped[str] = mapped_column(String(40), default="CSV_IMPORT")
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    __table_args__ = (UniqueConstraint("employee_id", "rpn_number"),)


class EmployeeBenefit(Base):
    """Recurring benefit configuration valued by the BIK engine each period."""

    __tablename__ = "employee_benefits"
    benefit_id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.employee_id", ondelete="CASCADE"), index=True)
    benefit_type: Mapped[str] = mapped_column(String(30))
    description: Mapped[str | None] = mapped_column(String(200))
    omv: Mapped[Decimal | None] = mapped_column(Money)
    co2_g_km: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    business_km: Mapped[int | None] = mapped_column(Integer)
    employee_contribution_annual: Mapped[Decimal] = mapped_column(Money, default=0)
    annual_value: Mapped[Decimal | None] = mapped_column(Money)
    period_value: Mapped[Decimal | None] = mapped_column(Money)
    active_from: Mapped[date | None] = mapped_column(Date)
    active_to: Mapped[date | None] = mapped_column(Date)
    employee: Mapped[Employee] = relationship(back_populates="benefits")


# ------------------------------------------------------------------ payroll


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    payroll_run_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    payroll_period: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    payment_date: Mapped[date] = mapped_column(Date)
    frequency: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    run_type: Mapped[str] = mapped_column(String(20), default="REGULAR")  # REGULAR | CORRECTION
    reverses_run_id: Mapped[int | None] = mapped_column(ForeignKey("payroll_runs.payroll_run_id"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totals: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    calc_seconds: Mapped[float | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','CALCULATING','VALIDATION_REQUIRED','READY_FOR_APPROVAL','APPROVED',"
            "'SUBMITTED','COMPLETED','REVERSED')", name="status_valid"),
        Index("ix_run_company_period", "company_id", "tax_year", "frequency", "payroll_period"),
    )


class PayrollInputRecord(Base):
    __tablename__ = "payroll_inputs"
    input_id: Mapped[int] = mapped_column(primary_key=True)
    payroll_run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.payroll_run_id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.employee_id"), index=True)
    insurable_weeks: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    earnings: Mapped[list[PayrollEarning]] = relationship(cascade="all, delete-orphan")
    deductions: Mapped[list[PayrollDeduction]] = relationship(
        primaryjoin="PayrollInputRecord.input_id == PayrollDeduction.input_id", cascade="all, delete-orphan",
        overlaps="result_deductions")
    __table_args__ = (UniqueConstraint("payroll_run_id", "employee_id"),)


class PayrollEarning(Base):
    __tablename__ = "payroll_earnings"
    earning_id: Mapped[int] = mapped_column(primary_key=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("payroll_inputs.input_id", ondelete="CASCADE"), index=True)
    earning_type: Mapped[str] = mapped_column(String(30))
    description: Mapped[str | None] = mapped_column(String(200))
    hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    amount: Mapped[Decimal] = mapped_column(Money)


class PayrollDeduction(Base):
    """Both user-entered post-tax deductions (input_id set) and calculated deduction lines (result_id set)."""

    __tablename__ = "payroll_deductions"
    deduction_id: Mapped[int] = mapped_column(primary_key=True)
    input_id: Mapped[int | None] = mapped_column(ForeignKey("payroll_inputs.input_id", ondelete="CASCADE"), index=True)
    result_id: Mapped[int | None] = mapped_column(ForeignKey("payroll_results.result_id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    description: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Money)
    __table_args__ = (CheckConstraint("amount >= 0", name="deduction_non_negative"),)


class PayrollResultRecord(Base):
    __tablename__ = "payroll_results"
    result_id: Mapped[int] = mapped_column(primary_key=True)
    payroll_run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.payroll_run_id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.employee_id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    gross_pay: Mapped[Decimal] = mapped_column(Money, default=0)
    bik: Mapped[Decimal] = mapped_column(Money, default=0)
    pay_for_tax: Mapped[Decimal] = mapped_column(Money, default=0)
    pay_for_usc: Mapped[Decimal] = mapped_column(Money, default=0)
    pay_for_prsi: Mapped[Decimal] = mapped_column(Money, default=0)
    gross_tax: Mapped[Decimal] = mapped_column(Money, default=0)
    tax_credits: Mapped[Decimal] = mapped_column(Money, default=0)
    paye: Mapped[Decimal] = mapped_column(Money, default=0)
    usc: Mapped[Decimal] = mapped_column(Money, default=0)
    prsi_ee: Mapped[Decimal] = mapped_column(Money, default=0)
    prsi_er: Mapped[Decimal] = mapped_column(Money, default=0)
    prsi_class: Mapped[str | None] = mapped_column(String(2))
    prsi_subclass: Mapped[str | None] = mapped_column(String(4))
    insurable_weeks: Mapped[int] = mapped_column(Integer, default=0)
    lpt: Mapped[Decimal] = mapped_column(Money, default=0)
    pension_ee: Mapped[Decimal] = mapped_column(Money, default=0)
    pension_er: Mapped[Decimal] = mapped_column(Money, default=0)
    other_deductions: Mapped[Decimal] = mapped_column(Money, default=0)
    net_pay: Mapped[Decimal] = mapped_column(Money, default=0)
    employer_cost: Mapped[Decimal] = mapped_column(Money, default=0)
    statutory_liability: Mapped[Decimal] = mapped_column(Money, default=0)
    tax_basis_applied: Mapped[str | None] = mapped_column(String(20))
    usc_status_applied: Mapped[str | None] = mapped_column(String(20))
    ytd: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    trace: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType)
    messages: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType)
    rules_used: Mapped[list[str] | None] = mapped_column(JSONType)
    earnings_detail: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    result_deductions: Mapped[list[PayrollDeduction]] = relationship(
        primaryjoin="PayrollResultRecord.result_id == PayrollDeduction.result_id", cascade="all, delete-orphan",
        overlaps="deductions")
    employee: Mapped[Employee] = relationship()
    __table_args__ = (UniqueConstraint("payroll_run_id", "employee_id"),)


class PayrollException(Base):
    __tablename__ = "payroll_exceptions"
    exception_id: Mapped[int] = mapped_column(primary_key=True)
    payroll_run_id: Mapped[int | None] = mapped_column(ForeignKey("payroll_runs.payroll_run_id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.employee_id"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # ENGINE | VALIDATION | ANOMALY | RECONCILIATION
    code: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(10), index=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN | ACKNOWLEDGED | RESOLVED
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("severity IN ('INFO','WARNING','ERROR','CRITICAL')", name="severity_valid"),)


class AuditLog(Base):
    __tablename__ = "payroll_audit_logs"
    audit_id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    user_email: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    before_value: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    after_value: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    reason: Mapped[str | None] = mapped_column(Text)


class Payslip(Base):
    __tablename__ = "payslips"
    payslip_id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("payroll_results.result_id", ondelete="CASCADE"), unique=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.employee_id"), index=True)
    payroll_run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.payroll_run_id", ondelete="CASCADE"), index=True)
    html: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RevenueSubmission(Base):
    __tablename__ = "revenue_submissions"
    submission_id: Mapped[int] = mapped_column(primary_key=True)
    payroll_run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.payroll_run_id", ondelete="CASCADE"), index=True)
    submission_ref: Mapped[str] = mapped_column(String(40), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="PREPARED")  # PREPARED | VALIDATION_FAILED | EXPORTED
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    validation_errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType)
    prepared_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ------------------------------------------------------------------ statutory rules


class _RuleColumns:
    rule_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    rule_set_id: Mapped[str] = mapped_column(String(20), index=True)
    jurisdiction: Mapped[str] = mapped_column(String(4), default="IE")
    tax_year: Mapped[int] = mapped_column(Integer, index=True)
    category: Mapped[str] = mapped_column(String(20))
    parameter: Mapped[str] = mapped_column(String(80))
    value: Mapped[Any] = mapped_column(JSONType)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_authority: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str] = mapped_column(Text)
    source_document: Mapped[str] = mapped_column(Text)
    verified_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="UNVERIFIED")
    notes: Mapped[str | None] = mapped_column(Text)


class TaxRule(_RuleColumns, Base):
    __tablename__ = "tax_rules"  # PAYE + EMERGENCY


class UscRule(_RuleColumns, Base):
    __tablename__ = "usc_rules"


class PrsiRule(_RuleColumns, Base):
    __tablename__ = "prsi_rules"


class LptRule(_RuleColumns, Base):
    __tablename__ = "lpt_rules"


class PensionRule(_RuleColumns, Base):
    __tablename__ = "pension_rules"


class BikRule(_RuleColumns, Base):
    __tablename__ = "bik_rules"


RULE_TABLES: dict[str, type] = {
    "PAYE": TaxRule, "EMERGENCY": TaxRule, "USC": UscRule, "PRSI": PrsiRule,
    "LPT": LptRule, "PENSION": PensionRule, "BIK": BikRule,
}
