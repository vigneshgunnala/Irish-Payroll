from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Freq = Literal["WEEKLY", "FORTNIGHTLY", "MONTHLY"]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class CompanyIn(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    trading_name: str | None = None
    tax_registration_number: str = Field(min_length=7, max_length=20)
    employer_registration_details: str | None = None
    address: str | None = None
    contact_email: EmailStr | None = None
    phone: str | None = None
    payroll_frequency: Freq = "MONTHLY"
    financial_year: int = Field(ge=2025, le=2030)


class CompanyOut(CompanyIn):
    model_config = ConfigDict(from_attributes=True)
    company_id: int
    contact_email: str | None = None


class EmployeeIn(BaseModel):
    company_id: int
    employee_number: str = Field(min_length=1, max_length=20)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    ppsn: str | None = None
    date_of_birth: date | None = None
    employment_start_date: date
    employment_end_date: date | None = None
    department_id: int | None = None
    job_title: str | None = None
    location: str | None = None
    contract_type: str | None = None
    salary_type: Literal["SALARY", "HOURLY"] = "SALARY"
    annual_salary: Decimal | None = Field(default=None, ge=0)
    hourly_rate: Decimal | None = Field(default=None, ge=0)
    standard_hours: Decimal | None = Field(default=None, ge=0, le=168)
    pay_frequency: Freq = "MONTHLY"
    prsi_class: str | None = Field(default="A", max_length=2)
    pension_scheme: Literal["OCCUPATIONAL", "AVC", "PRSA", "RAC"] | None = None
    pension_ee_percent: Decimal | None = Field(default=None, ge=0, le=1)
    pension_er_percent: Decimal | None = Field(default=None, ge=0, le=1)
    employment_id: str | None = None

    @field_validator("employment_end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        if v and info.data.get("employment_start_date") and v < info.data["employment_start_date"]:
            raise ValueError("employment_end_date before start date")
        return v


class EmployeeOut(BaseModel):
    employee_id: int
    employee_number: str
    name: str
    ppsn_masked: str
    department: str | None
    job_title: str | None
    pay_frequency: str
    salary_type: str
    annual_salary: Decimal | None
    prsi_class: str | None
    employment_status: str
    has_rpn: bool


class RunIn(BaseModel):
    company_id: int
    tax_year: int
    frequency: Freq
    payroll_period: int = Field(ge=1, le=53)
    period_start: date
    period_end: date
    payment_date: date


class EarningIn(BaseModel):
    type: str
    amount: Decimal
    description: str | None = None
    hours: Decimal | None = None


class DeductionIn(BaseModel):
    code: str
    amount: Decimal = Field(ge=0)
    description: str | None = None


class InputsIn(BaseModel):
    employee_id: int
    earnings: list[EarningIn] = []
    deductions: list[DeductionIn] = []


class ReasonIn(BaseModel):
    reason: str = Field(min_length=5)


class ExceptionResolveIn(BaseModel):
    note: str = Field(min_length=3)
    status: Literal["RESOLVED", "ACKNOWLEDGED"] = "RESOLVED"


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    payroll_run_id: int
    company_id: int
    tax_year: int
    payroll_period: int
    frequency: str
    period_start: date
    period_end: date
    payment_date: date
    status: str
    run_type: str
    totals: dict[str, Any] | None
    calc_seconds: float | None
