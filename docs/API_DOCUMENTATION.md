# API documentation

FastAPI serves interactive OpenAPI docs at **`/docs`** (Swagger) and **`/redoc`**; the schema is exported to
[`openapi.json`](openapi.json). All endpoints except `/health` and `/auth/token` require a Bearer JWT, and each is
guarded by a permission (see [SECURITY.md](SECURITY.md)).

## Authentication

```bash
curl -X POST localhost:8000/auth/token -d "username=payroll.admin@demo.ie&password=$PAYROLL_DEMO_PASSWORD"
# → {"access_token": "...", "token_type": "bearer", "role": "PAYROLL_ADMIN"}
export H="Authorization: Bearer <token>"
```

## Endpoints

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/auth/token` | – | Log in (OAuth2 password form) |
| GET | `/auth/me` | any | Current user |
| POST | `/companies` | company:write | Create company |
| GET | `/companies/{id}` | any | Company |
| POST | `/employees` | employee:write | Create employee (PPSN checksum validated) |
| GET | `/employees?company_id&search&department` | employee:read | List (PPSN masked) |
| GET | `/employees/{id}` | employee:read | Detail incl. tax profile & benefits |
| PATCH | `/employees/{id}?reason=` | employee:write | Audited change (salary changes logged as SALARY_CHANGED) |
| POST | `/rpn/import?company_id&tax_year` | tax_profile:write | Upload RPN CSV; returns imported count + per-line errors |
| POST | `/payroll-runs` | payroll:run | Create run (duplicate period → 409) |
| GET | `/payroll-runs`, `/payroll-runs/{id}` | payroll:read | Runs with totals |
| POST | `/payroll-runs/{id}/inputs` | payroll:run | Variable earnings/deductions for an employee |
| POST | `/payroll-runs/{id}/calculate` | payroll:run | Bulk calculation + validation + anomalies + reconciliation |
| POST | `/payroll-runs/{id}/validate` | payroll:run | Blocking count, exceptions by severity, reconciliation |
| POST | `/payroll-runs/{id}/approve` | payroll:approve | Approve (blocked by ERROR/CRITICAL) → locks run, generates payslips |
| POST | `/payroll-runs/{id}/reverse` | payroll:approve | Reverse with reason → creates CORRECTION run with inputs copied |
| GET | `/payroll-runs/{id}/results` | payroll:read | Payroll register |
| GET | `/payroll-results/{id}/explain?component=PAYE` | payroll:read | **Calculation trace with rule sources** |
| GET | `/payroll-runs/{id}/reconciliation` | reports:read | Reconciliation checks |
| GET | `/payroll-runs/{id}/journal?fmt=json\|csv` | reports:read | GL journal (+ balanced flag) |
| GET | `/payroll-runs/{id}/export.xlsx` | reports:read | Summary, register, liabilities, journal workbook |
| GET | `/employees/{id}/payslip?run_id&fmt=html\|pdf` | payroll:read | Payslip for an approved run |
| GET | `/exceptions?run_id&severity&status` | payroll:read | Exception queue |
| POST | `/exceptions/{id}/resolve` | payroll:run | Resolve/acknowledge with note (CRITICAL cannot be acknowledged) |
| GET | `/rules`, `/rules/tax`, `/rules/usc`, `/rules/prsi` | rules:read | Rules with value, dates, source, status |
| POST | `/rules/{rule_id}/status?status=` | rules:write | Verify/unverify with evidence (audited) |
| GET | `/analytics/payroll?company_id&tax_year&period` | analytics:read | Trend, department and variance analysis |
| POST | `/revenue/submission/prepare?run_id` | revenue:prepare | Build + validate submission data (no transmission) |
| GET | `/revenue/submission/{id}/export` | revenue:prepare | Download prepared JSON |
| GET | `/audit?limit&action` | audit:read | Audit log |
| GET | `/health` | – | DB connectivity |

## Example: why is PAYE what it is?

```bash
curl -H "$H" "localhost:8000/payroll-results/1669/explain?component=PAYE"
```
```json
{"paye": "877.99",
 "trace": [
  {"step": "Basis selection",       "calculation": "RPN tax basis = CUMULATIVE", "result": "CUMULATIVE"},
  {"step": "Periodise RPN",         "calculation": "cut-off €53,000.00 ÷ 12 = €4,416.67; credits €6,000.00 ÷ 12 = €500.00"},
  {"step": "Cumulative pay",        "calculation": "prior employment €0.00 + this employment YTD €38,623.38 + this period €5,653.34", "result": "44276.72"},
  {"step": "Cumulative allowances", "calculation": "cut-off €4,416.67 × 8 = €35,333.36; credits €500.00 × 8 = €4,000.00"},
  {"step": "Standard-rate portion", "calculation": "min(€44,276.72, €35,333.36) = €35,333.36 × 20%", "result": "7066.67",
   "rule": {"rule_id": "PAYE-2026-RATE-STD", "source": "Revenue Commissioners",
            "source_url": "https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx",
            "verified_date": "2026-09-21", "status": "VERIFIED"}},
  {"step": "Higher-rate portion",   "calculation": "max(€44,276.72 − €35,333.36, 0) = €8,943.36 × 40%", "result": "3577.34"},
  {"step": "Gross tax",             "calculation": "€7,066.67 + €3,577.34", "result": "10644.01"},
  {"step": "Tax credits",           "calculation": "max(€10,644.01 − €4,000.00, 0)", "result": "6644.01"},
  {"step": "PAYE due",              "calculation": "€6,644.01 − (€0.00 + €5,766.02)", "result": "877.99"}
 ]}
```
(abridged from [`examples/example_calculation_trace.json`](examples/example_calculation_trace.json) — the real response also carries `component`, `description`, `inputs`, `rate` and full rule references on every step.)

Errors: `401` unauthenticated · `403` missing permission · `404` not found · `409` workflow conflict (locked run, duplicate period, blocking exceptions) · `422` validation (bad PPSN, missing reason, unknown field).
