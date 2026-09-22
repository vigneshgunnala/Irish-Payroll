# 💶 Irish Payroll Management & Compliance System

A portfolio-grade prototype of an Irish payroll platform: **gross-to-net for PAYE, USC, PRSI, LPT, pensions and BIK**, bulk payroll runs for 300+ employees, validation and exception queues, reconciliation, payslips, GL journals, Revenue submission *preparation*, payroll analytics and a full audit trail.

Every statutory value is a **versioned, sourced rule** (Revenue / Department of Social Protection), and the engine **refuses to use any rule that is not verified**. Every figure on every payslip can be opened to show *why* it is what it is.

> ⚠️ **Prototype, not certified payroll software.** Synthetic data only. It does not transmit anything to Revenue. See [LIMITATIONS.md](docs/LIMITATIONS.md).

![Dashboard](docs/images/dashboard.png)

---

## The problem

A 200–300 person Irish employer runs payroll every week or month under rules that change (Budget 2026 moved the USC 2% ceiling to €28,700; Class A PRSI rises again on **1 October 2026**). Spreadsheet-driven payroll has three failure modes: hard-coded rates that silently go stale, figures nobody can explain when an employee queries them, and no control between "calculated" and "paid".

## The solution

| Need | How this system handles it |
|---|---|
| Rates change over time | Rules live in versioned JSON → database tables with effective-from/to dates, source URL, verification date and status. A 2027 rule set never touches 2026 results. |
| Don't guess | `UNVERIFIED` or missing rules raise a blocking exception ("Unable to calculate reliably…"). Example: the 1 Oct 2026 PRSI rates for Classes J/B/C/D were first found only in a vendor knowledge base, so they were stored **UNVERIFIED** and October payroll for those classes was blocked — until I found them in DSP's SW14 guide and promoted them (audited). |
| Explain every number | A structured calculation trace per employee: *pay → cut-off → 20% portion → 40% portion → gross tax → credits → cumulative liability → already deducted → PAYE this period*, each step citing its rule and source. |
| Scale without more staff | One-click bulk run (≈0.7 s for 300 employees on SQLite, ≈0.9 s on PostgreSQL incl. validation, anomaly detection and reconciliation). |
| Control | Status workflow, severity-graded exception queue, CRITICAL issues cannot be acknowledged, approval blocked while ERROR/CRITICAL items are open, locked approved runs, reversal + correction runs, audit log with before/after values. |

## Architecture

```mermaid
flowchart LR
  UI[Streamlit UI<br/>role-aware pages] --> SVC
  API[FastAPI REST<br/>JWT + RBAC] --> SVC
  subgraph SVC[Service layer]
    RUN[Payroll runs & workflow] --> VAL[Validation]
    RUN --> ANO[Anomaly detection]
    RUN --> REC[Reconciliation]
    RUN --> PS[Payslips HTML/PDF]
    RUN --> RPT[Reports / GL journal]
    RUN --> REV[Revenue submission prep]
    AUD[Audit log]
  end
  RUN --> ENG
  subgraph ENG[Payroll engine - pure Python, no DB/UI]
    PAYE --- USC --- PRSI --- LPT --- PEN[Pension] --- BIK
  end
  ENG --> RULES[(Rule repository<br/>versioned, sourced, verification-gated)]
  SVC --> DB[(PostgreSQL / SQLite)]
  RULES -. synced from .-> JSON[rules/data/ie_2026.json]
```

Layers are strictly separated: **data** (SQLAlchemy models) · **statutory rules** (JSON + rule tables) · **calculation engine** (pure functions over dataclasses — 77 engine unit tests run in 0.2 s with no database) · **validation** · **reporting** · **UI** · **integrations**. Details: [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Technology

Python 3.11 · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL (SQLite for local demo) · Pydantic v2 · pandas · Plotly · Streamlit · ReportLab · pytest · Ruff · mypy · Docker Compose.

## Irish payroll concepts implemented

| Area | Implemented |
|---|---|
| **PAYE** | Cumulative, Week 1/Month 1, emergency (with/without PPSN), RPN credits & cut-off, previous-employment pay/tax, refunds on the cumulative basis, Revenue's round-up-to-the-cent period figures |
| **USC** | Band-by-band (0.5 / 2 / 3 / 8%, 2026 ceiling €28,700), cumulative & non-cumulative, RPN exempt / reduced status, emergency 8% |
| **PRSI** | Class/subclass framework: A (J0/A0/AX/AL/A1 with tapered credit), B, C, D, H, J, K, M, S; weekly thresholds scaled 52/12 for monthly pay; **rates chosen by pay date so 1 Oct 2026 changes apply automatically** |
| **LPT** | Deduct only what the RPN instructs, spread equally, final-period true-up |
| **Pension** | Net pay arrangement: PAYE relief only (no USC/PRSI relief), age-related % limits, €115,000 cap, RAC not relieved via payroll |
| **BIK** | Pluggable valuers: company car (OMV − 2026 reduction, EV reduction, CO₂ category × business-km %, employee contributions), medical insurance (gross premium), small benefit exemption (5 / €1,500), other (manual cash equivalent) |
| **Employer** | Employer PRSI, employer pension, total employer cost, statutory liability, GL journal |

All figures and their sources: [PAYROLL_RULES.md](docs/PAYROLL_RULES.md).

## Screenshots

| | |
|---|---|
| ![Calculation drill-down](docs/images/calculation.png) *Why is each figure what it is?* | ![Exceptions](docs/images/exceptions.png) *Exception queue* |
| ![Runs](docs/images/runs.png) *Payroll run workflow* | ![Rules](docs/images/rules.png) *Versioned, sourced rules* |
| ![Analytics](docs/images/analytics.png) *Payroll analyst views* | ![Payslips](docs/images/payslips.png) *Payslips* |

Example outputs in [`docs/examples`](docs/examples): a [payslip PDF](docs/examples/example_payslip.pdf), the [300-employee August run workbook](docs/examples/payroll_run_P8_2026.xlsx), its [GL journal](docs/examples/payroll_journal_P8_2026.csv), a [masked submission file](docs/examples/revenue_submission_P8_masked.json) and a full [calculation trace](docs/examples/example_calculation_trace.json).

## Installation & running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export PAYROLL_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
export PAYROLL_DEMO_PASSWORD='choose-a-demo-password'
python -m scripts.seed            # schema + rules + 5 demo users + 300 employees + Jan–Sep 2026 payroll (~50 s)

streamlit run ui/app.py           # UI  → http://localhost:8501  (payroll.admin@demo.ie / your demo password)
uvicorn app.api.main:app --reload # API → http://localhost:8000/docs
```

PostgreSQL: set `PAYROLL_DATABASE_URL=postgresql+psycopg://user:pass@host/db`, run `alembic upgrade head`, then `python -m scripts.seed`.
Docker: `cp .env.example .env` (edit secrets) → `docker compose up --build`. *(The Dockerfile/compose stack is provided but could not be executed in my build environment because the container registry was blocked — the steps it runs — `alembic upgrade head`, the seed, and the full test suite including the API — were verified directly against PostgreSQL 16.)*

Demo users (one per role): `payroll.admin@`, `payroll.analyst@`, `hr.admin@`, `finance.manager@`, `sys.admin@` — all `…@demo.ie`.

The seeded September monthly run deliberately contains a missing PRSI class (CRITICAL), a duplicated allowance and a 120-hour overtime claim so the exception queue and approval block can be demonstrated.

## Testing

```bash
pytest                 # 110 tests, ~15 s  (engine, rules, workflow, API)
pytest --cov=app       # 91% overall; PAYE/USC 100%, PRSI 96%
ruff check . && mypy
python -m scripts.benchmark   # 100 / 300 / 500 / 1,000 employees
```

The same suite passes on SQLite and on PostgreSQL 16 (`PAYROLL_TEST_DATABASE_URL=postgresql+psycopg://…`). Regression tests reproduce DSP's own PRSI-credit worked example (€377/week → €8.00) and Revenue's published emergency cut-offs. See [TESTING.md](docs/TESTING.md).

## Limitations (summary)

Not certified by Revenue; no live Revenue API; fortnightly emergency basis and 2025 PRSI blocked (no verified rule); monthly PRSI-credit scaling is an interpretation; no week-53, no share-based remuneration, no PHB/income-continuance, no bank file. Full list: [LIMITATIONS.md](docs/LIMITATIONS.md).

## Future improvements

Certified Revenue integration (RPN retrieval + payroll submission via ROS certificate), week-53 and multiple-employment handling, bank (SEPA) payment file, leave/attendance integration, React front end on the existing API, role-based row-level security in PostgreSQL.

## Documentation

[ARCHITECTURE](docs/ARCHITECTURE.md) · [PAYROLL_RULES](docs/PAYROLL_RULES.md) · [DATABASE_SCHEMA](docs/DATABASE_SCHEMA.md) · [API_DOCUMENTATION](docs/API_DOCUMENTATION.md) · [TESTING](docs/TESTING.md) · [REVENUE_INTEGRATION](docs/REVENUE_INTEGRATION.md) · [SECURITY](docs/SECURITY.md) · [LIMITATIONS](docs/LIMITATIONS.md) · [CAREER_PORTFOLIO](docs/CAREER_PORTFOLIO.md)

## What I learned

- **Irish payroll is RPN-driven.** The employer doesn't decide credits, cut-off, USC status or LPT — Revenue does, via the RPN. The engine therefore treats the RPN as authoritative and only falls back to the emergency basis (and says why) when there is none.
- **Cumulative PAYE is a running reconciliation, not a monthly calculation**: new cumulative liability minus tax already deducted. That's why refunds happen automatically and why a correction run must rebuild YTD from the prior period, not stack on the reversed one (a test proves an unchanged correction reproduces the original figures to the cent).
- **USC and PRSI follow different rules from PAYE**: pension contributions reduce pay for tax but not for USC or PRSI; BIK increases all three; PRSI is always per-period, with employee and employer rates applied to *all* reckonable pay once a threshold is crossed.
- **Rounding is a rule too.** Revenue publishes €44,000/52 as €846.16 — rounded up — so the engine stores the rounding convention as a sourced rule.
- **Dates matter inside a tax year.** The PRSI increase on 1 October 2026 means two pay dates in the same month can use different rates; rules are selected by pay date.
- **Payroll data modelling, validation, reconciliation and auditability** matter as much as the maths: a correct number that can't be explained, reconciled or traced to an approver isn't payroll-ready.
- **Analytics supports, never decides.** Z-score and period-on-period checks flag unusual overtime, bonuses and net-pay drops for review; they never alter a statutory figure.
