"""Create schema, load verified rules, users, 300 synthetic employees and a year of payroll history.

    python -m scripts.seed               # uses PAYROLL_DATABASE_URL (default sqlite:///./payroll.db)
    PAYROLL_DEMO_PASSWORD=... python -m scripts.seed --employees 300
"""

from __future__ import annotations

import argparse
import os
import time

from sqlalchemy import select

from app.core.logging import configure_logging
from app.db.base import Base, get_engine, init_db, session_scope
from app.db.models import Company, User
from app.services.rules_service import sync_rules
from app.services.seed import ensure_roles_and_users, process_year, seed_company


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--employees", type=int, default=300)
    ap.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    ap.add_argument("--no-history", action="store_true")
    args = ap.parse_args()
    configure_logging("WARNING")
    if args.reset:
        Base.metadata.drop_all(get_engine())
    init_db()
    t0 = time.perf_counter()
    with session_scope() as s:
        n = sync_rules(s)
        print(f"rules synchronised: {n}")
        creds = ensure_roles_and_users(s, os.environ.get("PAYROLL_DEMO_PASSWORD"))
        if s.scalar(select(Company)) is None:
            co = seed_company(s, args.employees)
            print(f"company {co.company_id} with {args.employees} synthetic employees")
            if not args.no_history:
                admin = s.scalar(select(User).where(User.role == "PAYROLL_ADMIN"))
                out = process_year(s, co, admin)
                print(f"monthly runs: {out['monthly']}")
                print(f"weekly runs: {len(out['weekly'])} (last: {out['weekly'][-1]})")
    if creds:
        print("\nDemo users created (store these - they are not shown again):")
        for email, pw in creds.items():
            print(f"  {email:28s} {pw}")
    print(f"done in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
