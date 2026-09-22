"""First-start bootstrap for hosted demos (Streamlit Cloud, Render).

Always: create missing tables and sync the versioned rule files into the rule tables.
If PAYROLL_AUTO_SEED=true and the database has no company yet: create the demo users and the
synthetic company with its 2026 payroll history. Safe to call on every start.
"""

from __future__ import annotations

import logging
import secrets
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import DEMO_VIEWER_EMAIL, Role, hash_password, verify_password
from app.db.base import init_db, session_scope
from app.db.models import Company, User
from app.services.rules_service import sync_rules

log = logging.getLogger("payroll.bootstrap")


def ensure_demo_viewer(session) -> User:
    """Read-only account the public demo signs visitors into. Its password is random and never shown."""
    from app.services.seed import ensure_role_records

    ensure_role_records(session)
    u = session.scalar(select(User).where(User.email == DEMO_VIEWER_EMAIL))
    if u is None:
        u = User(email=DEMO_VIEWER_EMAIL, full_name="Demo Visitor", role=Role.DEMO_VIEWER.value,
                 password_hash=hash_password(secrets.token_urlsafe(32)))
        session.add(u)
        session.flush()
    return u


def sync_demo_passwords(session, password: str) -> int:
    """Keep the five demo logins on the *current* PAYROLL_DEMO_PASSWORD, so rotating the secret takes effect
    on the next restart even when the database persists (e.g. PostgreSQL)."""
    n = 0
    for u in session.scalars(select(User).where(User.email.like("%@demo.ie"), User.role != Role.DEMO_VIEWER.value)):
        if not verify_password(password, u.password_hash):
            u.password_hash = hash_password(password)
            n += 1
    return n


def ensure_ready() -> dict:
    s_ = get_settings()
    init_db()
    out = {"seeded": False}
    with session_scope() as s:
        out["rules_changed"] = sync_rules(s)
        seeded_already = s.scalar(select(Company)) is not None
        if seeded_already and s_.auto_seed and s_.demo_password:
            out["passwords_updated"] = sync_demo_passwords(s, s_.demo_password)
        if s_.public_demo:
            ensure_demo_viewer(s)
        if not s_.auto_seed or seeded_already:
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
        if s_.public_demo:
            ensure_demo_viewer(s)
    out["seeded"] = True
    log.warning("Demo data seeded in %.1fs", time.perf_counter() - t0)
    return out
