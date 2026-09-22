"""First-start bootstrap for hosted demos (Streamlit Cloud, Render).

Always: create missing tables and sync the versioned rule files into the rule tables.
If PAYROLL_AUTO_SEED=true and the database has no company yet: create the demo users and the
synthetic company with its 2026 payroll history. Safe to call on every start.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.db.base import init_db, session_scope
from app.db.models import Company, User
from app.services.rules_service import sync_rules

log = logging.getLogger("payroll.bootstrap")


def ensure_ready() -> dict:
    s_ = get_settings()
    init_db()
    out = {"seeded": False}
    with session_scope() as s:
        out["rules_changed"] = sync_rules(s)
        if not s_.auto_seed or s.scalar(select(Company)) is not None:
            return out
    if not s_.demo_password:
        raise RuntimeError("PAYROLL_AUTO_SEED is on but PAYROLL_DEMO_PASSWORD is not set")
    from app.services.seed import ensure_roles_and_users, process_year, seed_company

    t0 = time.perf_counter()
    with session_scope() as s:
        ensure_roles_and_users(s, s_.demo_password)
        co = seed_company(s, s_.seed_employees)
        admin = s.scalar(select(User).where(User.role == "PAYROLL_ADMIN"))
        if s_.seed_history:
            process_year(s, co, admin)
    out["seeded"] = True
    log.warning("Demo data seeded in %.1fs", time.perf_counter() - t0)
    return out
