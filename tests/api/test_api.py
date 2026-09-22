"""REST API: authentication, role permissions and the main payroll endpoints."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import Base, get_engine, init_db, session_scope
from app.db.models import User
from app.services.rules_service import sync_rules
from app.services.seed import ensure_roles_and_users, process_year, seed_company

PW = "api-test-password-1"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    url = os.environ.get("PAYROLL_TEST_DATABASE_URL") or f"sqlite:///{tmp_path_factory.mktemp('api') / 'api.db'}"
    Base.metadata.drop_all(get_engine(url))
    init_db(url)
    with session_scope() as s:
        sync_rules(s)
        ensure_roles_and_users(s, PW)
        co = seed_company(s, n_employees=40, seed=5)
        process_year(s, co, s.scalar(select(User).where(User.role == "PAYROLL_ADMIN")),
                     finalise_months=1, current_month=2, finalise_weeks=0, current_week=0)
    from app.api.main import app
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(get_engine())


def auth(c, email):
    r = c.post("/auth/token", data={"username": email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_requires_auth(client):
    assert client.get("/employees").status_code == 401
    assert client.post("/auth/token", data={"username": "payroll.admin@demo.ie", "password": "wrong"}).status_code == 401


def test_role_permissions(client):
    hr = auth(client, "hr.admin@demo.ie")
    assert client.get("/employees", headers=hr).status_code == 200
    assert client.post("/payroll-runs/1/calculate", headers=hr).status_code == 403
    fin = auth(client, "finance.manager@demo.ie")
    assert client.get("/payroll-runs/1/journal", headers=fin).status_code == 200
    assert client.post("/payroll-runs/2/approve", headers=fin).status_code == 403


def test_employee_list_masks_ppsn(client):
    rows = client.get("/employees?company_id=1", headers=auth(client, "payroll.admin@demo.ie")).json()
    assert len(rows) == 40
    assert all(r["ppsn_masked"] == "—" or r["ppsn_masked"].startswith("•") for r in rows)


def test_create_employee_validates_ppsn(client):
    h = auth(client, "hr.admin@demo.ie")
    body = {"company_id": 1, "employee_number": "API1", "first_name": "A", "last_name": "B", "ppsn": "1234567A",
            "employment_start_date": "2026-09-01", "annual_salary": "40000"}
    assert client.post("/employees", json=body, headers=h).status_code == 422
    body["ppsn"] = "1234567T"
    assert client.post("/employees", json=body, headers=h).status_code == 200


def test_explain_endpoint(client):
    h = auth(client, "payroll.admin@demo.ie")
    res = client.get("/payroll-runs/1/results", headers=h).json()
    ok = next(r for r in res if r["status"] == "CALCULATED")
    ex = client.get(f"/payroll-results/{ok['result_id']}/explain?component=PAYE", headers=h).json()
    assert ex["trace"] and all(t["component"] == "PAYE" for t in ex["trace"])
    assert any(t["rule"] and t["rule"]["source_url"].startswith("https://www.revenue.ie") for t in ex["trace"])


def test_run_lifecycle_via_api(client):
    h = auth(client, "payroll.admin@demo.ie")
    body = {"company_id": 1, "tax_year": 2026, "frequency": "MONTHLY", "payroll_period": 10, "period_start": "2026-10-01",
            "period_end": "2026-10-31", "payment_date": "2026-10-23"}
    run = client.post("/payroll-runs", json=body, headers=h).json()
    assert client.post("/payroll-runs", json=body, headers=h).status_code == 409  # duplicate period
    rid = run["payroll_run_id"]
    calc = client.post(f"/payroll-runs/{rid}/calculate", headers=h).json()
    assert calc["totals"]["employees_processed"] > 0
    val = client.post(f"/payroll-runs/{rid}/validate", headers=h).json()
    assert all(x["status"] == "OK" for x in val["reconciliation"])
    # October run uses the 1 October 2026 PRSI rates
    res = client.get(f"/payroll-runs/{rid}/results", headers=h).json()
    r = next(x for x in res if x["status"] == "CALCULATED" and x["prsi_subclass"] == "A1")
    ex = client.get(f"/payroll-results/{r['result_id']}/explain?component=PRSI", headers=h).json()
    assert "PRSI-2026-A-H2" in ex["rules_used"]
    if val["blocking"] == 0:
        assert client.post(f"/payroll-runs/{rid}/approve", headers=h).json()["status"] == "APPROVED"
        emp = r["employee_id"]
        assert client.get(f"/employees/{emp}/payslip?run_id={rid}&fmt=pdf", headers=h).content[:4] == b"%PDF"
        sub = client.post(f"/revenue/submission/prepare?run_id={rid}", headers=h).json()
        assert sub["status"] in ("PREPARED", "VALIDATION_FAILED")
        assert client.get(f"/revenue/submission/{sub['submission_id']}/export", headers=h).status_code == 200


def test_rules_endpoints(client):
    h = auth(client, "payroll.analyst@demo.ie")
    prsi = client.get("/rules/prsi", headers=h).json()
    assert {r["status"] for r in prsi} == {"VERIFIED"}
    assert all(r["source_url"] for r in prsi)
    assert client.get("/rules/usc", headers=h).status_code == 200
    sa = auth(client, "sys.admin@demo.ie")
    assert client.post("/rules/USC-2026-BANDS/status?status=VERIFIED", json={"reason": "x"}, headers=sa).status_code == 422


def test_analytics_and_audit(client):
    h = auth(client, "payroll.admin@demo.ie")
    a = client.get("/analytics/payroll?company_id=1", headers=h).json()
    assert a["trend"] and a["departments"]
    log = client.get("/audit?limit=20", headers=h).json()
    assert log and all("action" in x for x in log)
