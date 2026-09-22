"""Database-backed workflow tests: bulk runs, validation, approval, reconciliation, reversal, payslips, exports, audit."""

from __future__ import annotations

import os
import time
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from app.db.base import Base, get_engine, init_db, session_scope
from app.db.models import AuditLog, Company, Employee, PayrollException, PayrollResultRecord, PayrollRun, User
from app.services import payroll_service as ps
from app.services import reports
from app.services.employees import create_employee, import_rpn_csv, validate_ppsn
from app.services.payslips import generate_payslips, render_pdf
from app.services.reconciliation import reconcile_run
from app.services.revenue import prepare_submission
from app.services.rules_service import repository_from_db, set_rule_status, sync_rules
from app.services.seed import _month_bounds, _payday_monthly, ensure_roles_and_users, process_year, seed_company


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    url = os.environ.get("PAYROLL_TEST_DATABASE_URL") or f"sqlite:///{tmp_path_factory.mktemp('db') / 'test.db'}"
    Base.metadata.drop_all(get_engine(url))
    init_db(url)
    with session_scope() as s:
        sync_rules(s)
        ensure_roles_and_users(s, "test-password-123")
        co = seed_company(s, n_employees=60, seed=3)
        admin = s.scalar(select(User).where(User.role == "PAYROLL_ADMIN"))
        process_year(s, co, admin, finalise_months=2, current_month=3, finalise_weeks=2, current_week=3)
    yield url
    Base.metadata.drop_all(get_engine())


def _admin(s):
    return s.scalar(select(User).where(User.role == "PAYROLL_ADMIN"))


def _run(s, freq="MONTHLY", period=3):
    return s.scalar(select(PayrollRun).where(PayrollRun.frequency == freq, PayrollRun.payroll_period == period,
                                             PayrollRun.status != "REVERSED"))


def test_history_runs_completed(db):
    with session_scope() as s:
        st = dict(s.execute(select(PayrollRun.payroll_period, PayrollRun.status).where(PayrollRun.frequency == "MONTHLY")).all())
        assert st[1] == st[2] == "COMPLETED"
        assert st[3] in ("READY_FOR_APPROVAL", "VALIDATION_REQUIRED")


def test_run_totals_reconcile(db):
    with session_scope() as s:
        for run in s.scalars(select(PayrollRun)):
            assert all(x["status"] == "OK" for x in reconcile_run(s, run, record=False)), run.payroll_run_id


def test_injected_critical_blocks_approval(db):
    with session_scope() as s:
        run = _run(s)
        assert run.status == "VALIDATION_REQUIRED"
        codes = set(s.scalars(select(PayrollException.code).where(PayrollException.payroll_run_id == run.payroll_run_id)))
        assert {"PRSI_CLASS_MISSING", "PRSI_CLASS_INVALID", "DUPLICATE_EARNING"} <= codes
        with pytest.raises(ps.WorkflowError):
            run.status = "READY_FOR_APPROVAL"  # even if forced, approval re-checks exceptions
            ps.approve_run(s, _admin(s), run)
        run.status = "VALIDATION_REQUIRED"


def test_critical_cannot_be_acknowledged(db):
    with session_scope() as s:
        x = s.scalar(select(PayrollException).where(PayrollException.severity == "CRITICAL", PayrollException.status == "OPEN"))
        with pytest.raises(ps.WorkflowError):
            ps.resolve_exception(s, _admin(s), x, "looks fine", "ACKNOWLEDGED")


def test_fix_recalculate_approve_complete(db):
    with session_scope() as s:
        admin, run = _admin(s), _run(s)
        # fix data at source
        for e in s.scalars(select(Employee).where(Employee.prsi_class.is_(None))):
            e.prsi_class = "A"
        ps.calculate_run(s, admin, run)
        for x in s.scalars(select(PayrollException).where(PayrollException.payroll_run_id == run.payroll_run_id,
                                                          PayrollException.status == "OPEN",
                                                          PayrollException.severity.in_(("ERROR",)))):
            ps.resolve_exception(s, admin, x, "Reviewed and confirmed with manager", "RESOLVED")
        assert ps.blocking_exceptions(s, run) == 0
        assert run.status == "READY_FOR_APPROVAL"
        ps.approve_run(s, admin, run)
        assert run.locked_at is not None
        assert generate_payslips(s, admin, run) == run.totals["employees_successful"]
        with pytest.raises(ps.WorkflowError):
            ps.calculate_run(s, admin, run)  # locked
        sub = prepare_submission(s, admin, run)
        assert sub.status == "PREPARED" and len(sub.payload["payslips"]) == run.totals["employees_successful"]
        ps.mark_submitted(s, admin, run)
        ps.complete_run(s, admin, run)
        assert run.status == "COMPLETED"


def test_ytd_continuity_across_periods(db):
    with session_scope() as s:
        rows = s.execute(select(PayrollResultRecord, PayrollRun).join(PayrollRun).where(
            PayrollRun.frequency == "MONTHLY", PayrollRun.status == "COMPLETED", PayrollResultRecord.status == "CALCULATED")
            .order_by(PayrollRun.payroll_period)).all()
        by_emp: dict[int, list] = {}
        for r, _run in rows:
            by_emp.setdefault(r.employee_id, []).append(r)
        for results in by_emp.values():
            running = D(0)
            for r in results:
                running += r.paye
                assert D(r.ytd["tax"]) == running


def test_reversal_and_correction(db):
    with session_scope() as s:
        admin = _admin(s)
        run = _run(s, period=3)
        before = {r.employee_id: r.paye for r in s.scalars(select(PayrollResultRecord).where(
            PayrollResultRecord.payroll_run_id == run.payroll_run_id))}
        corr = ps.reverse_run(s, admin, run, "Bonus keyed to wrong employees")
        assert run.status == "REVERSED" and corr.run_type == "CORRECTION"
        ps.calculate_run(s, admin, corr)
        after = {r.employee_id: r.paye for r in s.scalars(select(PayrollResultRecord).where(
            PayrollResultRecord.payroll_run_id == corr.payroll_run_id))}
        # inputs are carried over and YTD comes from period 2 (the reversed period is not stacked on top),
        # so an unchanged correction reproduces the original figures exactly
        assert before.keys() == after.keys()
        assert all(before[k] == after[k] for k in before)


def test_duplicate_regular_run_rejected(db):
    with session_scope() as s:
        s_, e_ = _month_bounds(2026, 2)
        with pytest.raises(ps.WorkflowError, match="already exists"):
            ps.create_run(s, _admin(s), 1, 2026, "MONTHLY", 2, s_, e_, _payday_monthly(2026, 2))


def test_journal_balances_and_exports(db):
    with session_scope() as s:
        run = _run(s, period=2)
        lines = reports.journal(run)
        assert reports.journal_balanced(lines)
        assert reports.run_workbook(s, run)[:2] == b"PK"  # xlsx zip
        df = reports.register(s, run)
        assert not df["ppsn"].str.match(r"^\d{7}").any()  # PPSNs masked in reports
        r = s.scalar(select(PayrollResultRecord).where(PayrollResultRecord.payroll_run_id == run.payroll_run_id,
                                                       PayrollResultRecord.status == "CALCULATED"))
        assert render_pdf(s, r)[:4] == b"%PDF"


def test_leaver_prorated(db):
    with session_scope() as s:
        admin = _admin(s)
        emp = create_employee(s, admin, dict(company_id=1, employee_number="E9001", first_name="Test", last_name="Leaver",
                                             ppsn=None, date_of_birth=date(1990, 1, 1), employment_start_date=date(2020, 1, 1),
                                             employment_end_date=date(2026, 4, 15), pay_frequency="MONTHLY", prsi_class="A",
                                             salary_type="SALARY", annual_salary=D("36000"), employment_id="9001"))
        st, en = _month_bounds(2026, 4)
        run = ps.create_run(s, admin, 1, 2026, "MONTHLY", 4, st, en, _payday_monthly(2026, 4))
        ps.calculate_run(s, admin, run)
        r = s.scalar(select(PayrollResultRecord).where(PayrollResultRecord.payroll_run_id == run.payroll_run_id,
                                                       PayrollResultRecord.employee_id == emp.employee_id))
        assert r.gross_pay == D("1500.00")  # 3,000 × 15/30 days
        assert r.tax_basis_applied == "EMERGENCY"  # no PPSN, no RPN


def test_rpn_import_validates(db):
    with session_scope() as s:
        bad = ("employee_number,rpn_number,tax_basis,annual_tax_credits,annual_srcop,usc_status,effective_date\n"
               "E0001,RPNX1,CUMULATIVE,4000,44000,ORDINARY,2026-05-01\n"
               "E0002,RPNX2,NONSENSE,4000,44000,ORDINARY,2026-05-01\n"
               "ZZZ,RPNX3,CUMULATIVE,4000,44000,ORDINARY,2026-05-01\n")
        res = import_rpn_csv(s, _admin(s), 1, bad, 2026)
        assert res["imported"] == 1 and len(res["errors"]) == 2
        with pytest.raises(ValueError):
            import_rpn_csv(s, _admin(s), 1, "employee_number,rpn_number\nE1,R\n", 2026)


def test_ppsn_validation():
    assert validate_ppsn("1234567T") == (True, "ok")  # checksum example: 1*8+2*7+3*6+4*5+5*4+6*3+7*2 = 112 → 112 % 23 = 20 → T
    assert validate_ppsn("1234567A")[0] is False
    assert validate_ppsn("12AB")[1] == "format"


def test_unverifying_a_rule_blocks_calculation(db):
    with session_scope() as s:
        admin = s.scalar(select(User).where(User.role == "SYSTEM_ADMIN"))
        set_rule_status(s, "USC-2026-BANDS", "UNVERIFIED", admin, "Budget change announced - re-verify")
        repo = repository_from_db(s)
        from app.engine.calculator import PayrollEngine
        from tests.conftest import make_input
        assert PayrollEngine(repo).calculate(make_input("4000")).status.value == "UNVERIFIED"
        set_rule_status(s, "USC-2026-BANDS", "VERIFIED", admin, "Re-verified against revenue.ie")


def test_audit_trail_records_actions(db):
    with session_scope() as s:
        actions = set(s.scalars(select(AuditLog.action)))
        for a in ("EMPLOYEE_CREATED", "RPN_IMPORTED", "TAX_PROFILE_CHANGED", "PAYROLL_CALCULATED", "PAYROLL_RECALCULATED",
                  "PAYROLL_APPROVED", "PAYROLL_REVERSED", "PAYSLIPS_GENERATED", "SUBMISSION_PREPARED", "RULE_STATUS_CHANGED"):
            assert a in actions, a
        # no raw PPSN in audit values
        import re
        for row in s.scalars(select(AuditLog).where(AuditLog.action == "EMPLOYEE_CREATED")):
            assert not re.search(r"\b\d{7}[A-W]", str(row.after_value))


@pytest.mark.parametrize("n", [300])
def test_bulk_300_employee_run_performance(n, tmp_path):
    url = os.environ.get("PAYROLL_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'bulk.db'}"
    Base.metadata.drop_all(get_engine(url))
    init_db(url)
    with session_scope() as s:
        sync_rules(s)
        ensure_roles_and_users(s, "test-password-123")
        co = seed_company(s, n_employees=n, seed=11)
        st, en = _month_bounds(2026, 1)
        run = ps.create_run(s, None, co.company_id, 2026, "MONTHLY", 1, st, en, _payday_monthly(2026, 1))
        t0 = time.perf_counter()
        totals = ps.calculate_run(s, None, run)
        elapsed = time.perf_counter() - t0
        monthly = s.scalar(select(func.count()).select_from(Employee).where(Employee.pay_frequency == "MONTHLY",
                                                                              Employee.company_id == co.company_id))
        assert totals["employees_processed"] <= monthly
        assert totals["employees_successful"] + totals["employees_with_errors"] == totals["employees_processed"]
        assert elapsed < 20
    Base.metadata.drop_all(get_engine())
    _ = Company


def test_demo_viewer_is_read_only():
    from app.core.security import ROLE_PERMISSIONS, WRITE_PERMS, Perm, Role

    viewer = ROLE_PERMISSIONS[Role.DEMO_VIEWER]
    assert not viewer & WRITE_PERMS
    assert {Perm.PAYROLL_READ, Perm.EMPLOYEE_READ, Perm.REPORTS, Perm.ANALYTICS} <= viewer
    # every permission that exists is classified as either read or write
    assert all(p in WRITE_PERMS or p.value.endswith(":read") for p in Perm)


def test_public_demo_viewer_and_password_rotation(tmp_path):
    from app.core.security import DEMO_VIEWER_EMAIL, verify_password
    from app.services.bootstrap import ensure_demo_viewer, sync_demo_passwords

    url = os.environ.get("PAYROLL_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'viewer.db'}"
    Base.metadata.drop_all(get_engine(url))
    init_db(url)
    with session_scope() as s:
        ensure_roles_and_users(s, "test-password-123")
        v1 = ensure_demo_viewer(s)
        v2 = ensure_demo_viewer(s)  # idempotent
        assert v1.user_id == v2.user_id and v1.role == "DEMO_VIEWER" and v1.email == DEMO_VIEWER_EMAIL
        assert not verify_password("test-password-123", v1.password_hash)
        assert sync_demo_passwords(s, "rotated-password-456") == 5
        assert sync_demo_passwords(s, "rotated-password-456") == 0
        admin = _admin(s)
        assert verify_password("rotated-password-456", admin.password_hash)
    Base.metadata.drop_all(get_engine())
