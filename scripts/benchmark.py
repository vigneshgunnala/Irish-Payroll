"""Bulk payroll benchmark: 100 / 300 / 500 / 1,000 employees.

Measures (a) the pure engine (no database) and (b) a full payroll run through the service layer
(load employees + YTD, calculate, persist results & traces, validation, anomaly detection, reconciliation).

    python -m scripts.benchmark [--db sqlite|postgres-url] [--out docs/BENCHMARKS.md]
"""

from __future__ import annotations

import argparse
import platform
import tempfile
import time
from pathlib import Path

from sqlalchemy import func, select

from app.db.base import Base, get_engine, init_db, session_scope
from app.db.models import PayrollRun
from app.engine.calculator import PayrollEngine
from app.services import payroll_service as ps
from app.services.rules_service import repository_from_db, sync_rules
from app.services.seed import _month_bounds, _payday_monthly, seed_company


def one(n: int, url: str) -> dict:
    Base.metadata.drop_all(get_engine(url))
    init_db(url)
    with session_scope() as s:
        sync_rules(s)
        co = seed_company(s, n_employees=n, seed=n)
        st, en = _month_bounds(2026, 1)
        runs = {}
        for freq in ("MONTHLY", "WEEKLY"):
            runs[freq] = ps.create_run(s, None, co.company_id, 2026, freq, 1, st if freq == "MONTHLY" else st,
                                       en if freq == "MONTHLY" else st.replace(day=7),
                                       _payday_monthly(2026, 1) if freq == "MONTHLY" else st.replace(day=2))
        engine = PayrollEngine(repository_from_db(s))
        # pure engine timing
        inputs = []
        for run in runs.values():
            priors = ps.prior_results(s, run)
            inputs += [ps.build_input(e, run, None, priors.get(e.employee_id)) for e in ps.eligible_employees(s, run)]
        t0 = time.perf_counter()
        results = [engine.calculate(i) for i in inputs]
        engine_s = time.perf_counter() - t0
        # full service-layer runs
        t0 = time.perf_counter()
        ok = err = 0
        for run in runs.values():
            t = ps.calculate_run(s, None, run, engine)
            ok += t["employees_successful"]
            err += t["employees_with_errors"]
        full_s = time.perf_counter() - t0
        assert s.scalar(select(func.count()).select_from(PayrollRun)) == 2
    return {"employees": n, "calculated": len(results), "successful": ok, "errors": err,
            "engine_s": engine_s, "engine_per_emp_ms": engine_s / max(len(results), 1) * 1000, "full_run_s": full_s}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="SQLAlchemy URL (default: temporary SQLite file)")
    ap.add_argument("--sizes", default="100,300,500,1000")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    url = a.db or f"sqlite:///{Path(tempfile.mkdtemp()) / 'bench.db'}"
    rows = [one(int(n), url) for n in a.sizes.split(",")]
    Base.metadata.drop_all(get_engine(url))
    dialect = url.split(":")[0]
    lines = ["| Employees | Calculated | Successful | Errors (blocked, by design) | Engine only (s) | ms / employee "
             "| Full run incl. DB, validation, anomalies, reconciliation (s) |",
             "|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['employees']:,} | {r['calculated']:,} | {r['successful']:,} | {r['errors']} | {r['engine_s']:.2f} | "
                     f"{r['engine_per_emp_ms']:.2f} | {r['full_run_s']:.2f} |")
    table = "\n".join(lines)
    header = f"Database: **{dialect}** · Python {platform.python_version()} · {platform.machine()} · single process\n\n"
    print(header + table)
    if a.out:
        Path(a.out).write_text(header + table + "\n")


if __name__ == "__main__":
    main()
