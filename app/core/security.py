"""Password hashing, JWT tokens, role permissions and PII masking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

import bcrypt
import jwt

from app.core.config import get_settings


class Role(str, Enum):
    PAYROLL_ADMIN = "PAYROLL_ADMIN"
    PAYROLL_ANALYST = "PAYROLL_ANALYST"
    HR_ADMIN = "HR_ADMIN"
    FINANCE_MANAGER = "FINANCE_MANAGER"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    DEMO_VIEWER = "DEMO_VIEWER"  # public portfolio demo: look at everything, change nothing


class Perm(str, Enum):
    EMPLOYEE_READ = "employee:read"
    EMPLOYEE_WRITE = "employee:write"
    TAX_PROFILE_WRITE = "tax_profile:write"
    PAYROLL_RUN = "payroll:run"
    PAYROLL_APPROVE = "payroll:approve"
    PAYROLL_READ = "payroll:read"
    REPORTS = "reports:read"
    ANALYTICS = "analytics:read"
    RULES_READ = "rules:read"
    RULES_WRITE = "rules:write"
    USERS_MANAGE = "users:manage"
    AUDIT_READ = "audit:read"
    REVENUE_PREPARE = "revenue:prepare"
    REVENUE_READ = "revenue:read"
    COMPANY_WRITE = "company:write"


ROLE_PERMISSIONS: dict[Role, set[Perm]] = {
    Role.PAYROLL_ADMIN: {
        Perm.EMPLOYEE_READ, Perm.EMPLOYEE_WRITE, Perm.TAX_PROFILE_WRITE, Perm.PAYROLL_RUN, Perm.PAYROLL_APPROVE,
        Perm.PAYROLL_READ, Perm.REPORTS, Perm.ANALYTICS, Perm.RULES_READ, Perm.REVENUE_PREPARE, Perm.REVENUE_READ, Perm.AUDIT_READ,
    },
    Role.PAYROLL_ANALYST: {Perm.EMPLOYEE_READ, Perm.PAYROLL_READ, Perm.REPORTS, Perm.ANALYTICS, Perm.RULES_READ},
    Role.HR_ADMIN: {Perm.EMPLOYEE_READ, Perm.EMPLOYEE_WRITE},
    Role.FINANCE_MANAGER: {Perm.PAYROLL_READ, Perm.REPORTS, Perm.ANALYTICS, Perm.RULES_READ},
    Role.SYSTEM_ADMIN: {
        Perm.USERS_MANAGE, Perm.RULES_READ, Perm.RULES_WRITE, Perm.AUDIT_READ, Perm.COMPANY_WRITE, Perm.EMPLOYEE_READ,
    },
    # read-only: every page, filter, drill-down and download - but no create/calculate/approve/edit/import permission
    Role.DEMO_VIEWER: {
        Perm.EMPLOYEE_READ, Perm.PAYROLL_READ, Perm.REPORTS, Perm.ANALYTICS, Perm.RULES_READ, Perm.AUDIT_READ, Perm.REVENUE_READ,
    },
}

WRITE_PERMS = frozenset({Perm.EMPLOYEE_WRITE, Perm.TAX_PROFILE_WRITE, Perm.PAYROLL_RUN, Perm.PAYROLL_APPROVE, Perm.RULES_WRITE,
                         Perm.USERS_MANAGE, Perm.REVENUE_PREPARE, Perm.COMPANY_WRITE})
DEMO_VIEWER_EMAIL = "demo.viewer@demo.ie"


def has_perm(role: str, perm: Perm) -> bool:
    try:
        return perm in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(subject: str, role: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "role": role, "iat": now, "exp": now + timedelta(minutes=s.access_token_minutes)}
    return jwt.encode(payload, s.effective_secret(), algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().effective_secret(), algorithms=["HS256"])


def mask_ppsn(ppsn: str | None) -> str:
    if not ppsn:
        return "—"
    p = ppsn.strip()
    return "•" * max(len(p) - 3, 0) + p[-3:]


def mask_iban(iban: str | None) -> str:
    if not iban:
        return "—"
    return iban[:4] + " •••• " + iban[-4:]
