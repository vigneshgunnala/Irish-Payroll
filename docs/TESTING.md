# Testing

## Results (this build, 22 September 2026)

* **110 tests pass** on SQLite **and** on PostgreSQL 16 (`PAYROLL_TEST_DATABASE_URL=postgresql+psycopg://…`).
* **Coverage 91%** overall — `paye.py` 100%, `usc.py` 100%, `prsi.py` 96%, `calculator.py` 96%, `components.py` 94%.
* `ruff check .` — all checks passed · `mypy` (engine + rules) — no issues.
* UI: all 15 Streamlit pages were opened in headless Chromium after login and screenshotted with no exceptions
  (`docs/images/*.png`).
* Docker: the Dockerfile/compose files were **not** executed — the build sandbox could not reach the container
  registry. The steps they run (Alembic migration, seed, API) were run directly against PostgreSQL 16.

Full coverage report: [test_results.txt](test_results.txt).

## Suites

| Suite | Tests | What it proves |
|---|---:|---|
| `tests/engine/test_paye.py` | 21 | Standard/low/high income; cumulative full-year = annual liability (±cents from Revenue rounding) for €30k/€60k/€120k; YTD continuation; refunds; Week 1/Month 1 ignores YTD; mid-year joiner with prior-employment pay/tax; salary change; emergency with/without PPSN (weekly weeks 1–4 → €846.16, monthly month 1 → €3,666.67, then 40%); fortnightly emergency **blocked**; missing RPN data **blocked**; trace structure and sources; married one-income; multiple earning types |
| `tests/engine/test_usc_prsi.py` | 32 | USC band-by-band, full-year €60k and €100k vs annual figures, exempt, reduced, non-cumulative, pension not relieved, missing status blocked, **2025 vs 2026 bands stored independently**, 2025 PRSI missing → blocked; PRSI: **DSP worked example €377/week → €8.00**, same case after 1 Oct → €8.57; all Class A thresholds (€352 / €424.01 / €552 / €552.01); < €38 → Class J (0.70%, and 0.85% from 1 Oct); monthly 52/12 thresholds and credit; **rate switch by pay date**; Classes S, M, J, B (before and after 1 Oct), H, K; an UNVERIFIED rule **blocks** the calculation; missing/invalid class blocked |
| `tests/engine/test_components_g2n.py` | 25 | LPT spread and final-period true-up; pension PAYE-only relief, age limit cap, €115k cap, RAC, DOB required; company car BIK (5 parametrised cases incl. EV and category E), BIK in all pay bases but not cash, medical insurance, small benefit exemption count/value limits; gross-to-net identities; zero pay; negative adjustment vs negative bonus; negative gross/net; tax-year mismatch; every traced rule VERIFIED and sourced; irregular pay pattern catches up cumulatively |
| `tests/services/test_rules.py` | 8 | Every rule has full metadata and an https source; only official domains may be VERIFIED; UNVERIFIED rules refused unless explicitly allowed; Oct-2026 J/B/C/D rates match SW14; overlapping effective dates rejected; 2026 headline values match official figures |
| `tests/services/test_workflow.py` | 15 | Seeded history completes; every run reconciles; injected CRITICAL blocks approval; CRITICAL cannot be acknowledged; fix → recalculate → resolve → approve → lock → payslips → submission → complete; YTD continuity across periods; **reversal + correction reproduces original figures exactly** (no double-counting); duplicate period rejected; journal balances, XLSX/PDF valid, PPSNs masked; leaver pro-rated and emergency-taxed; RPN import line errors; PPSN checksum; un-verifying a rule blocks calculation; audit actions recorded without raw PPSNs; **300-employee bulk run** |
| `tests/api/test_api.py` | 9 | Auth required, wrong password rejected, role permissions (HR can't calculate, Finance can't approve), PPSN masking, PPSN validation, explain endpoint with Revenue source, full run lifecycle incl. October PRSI rule version, rules endpoints, rule change requires a reason, analytics and audit |

## Official-source regression tests

| Test | Source | Expected |
|---|---|---|
| `test_dsp_prsi_credit_worked_example` | DSP Advance Notice 2026 — PRSI credit example (€377 gross weekly) | credit €7.83, PRSI €15.83, charge **€8.00** |
| `test_emergency_with_ppsn_weeks_1_to_4_then_higher_rate` | Revenue *Emergency Basis of Tax & USC Deduction*, 2026 table | weekly cut-off €846.16 weeks 1–4, €0 from week 5 |
| `test_emergency_monthly_month_1_cut_off` | same | €3,666.67 month 1, then €0 |
| `test_2026_values_match_official_figures` | Revenue tax relief chart, USC page, SW14 | 20%, €44,000, USC 12,012/28,700/70,044, Class A 4.2%/9%/11.25%, €552 |
| `test_prsi_monthly_thresholds_scale_52_over_12` | SW14 monthly bands (€1,525 / €2,392) | subclass and employer rate at the boundaries |

Revenue does not publish a full worked PAYE/USC example for 2026 on the pages checked, so PAYE/USC expectations are
derived by hand from the published bands (derivations are in the test comments) and cross-checked against the
annual liability over a full year.

## Benchmarks (`python -m scripts.benchmark`)

"Calculated" is lower than "Employees" because synthetic joiners/leavers are outside the January period.
"Full run" includes loading employees and YTD, calculation, persisting results + traces, validation, anomaly
detection and reconciliation (monthly + weekly runs).

Database: **sqlite** · Python 3.11.15 · x86_64 · single process

| Employees | Calculated | Successful | Errors (blocked, by design) | Engine only (s) | ms / employee | Full run incl. DB, validation, anomalies, reconciliation (s) |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 95 | 95 | 0 | 0.03 | 0.32 | 0.26 |
| 300 | 294 | 294 | 0 | 0.08 | 0.27 | 0.68 |
| 500 | 488 | 488 | 0 | 0.20 | 0.41 | 1.05 |
| 1,000 | 957 | 957 | 0 | 0.35 | 0.37 | 2.24 |


Database: **postgresql+psycopg** · Python 3.11.15 · x86_64 · single process

| Employees | Calculated | Successful | Errors (blocked, by design) | Engine only (s) | ms / employee | Full run incl. DB, validation, anomalies, reconciliation (s) |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 95 | 95 | 0 | 0.07 | 0.68 | 0.36 |
| 300 | 294 | 294 | 0 | 0.12 | 0.40 | 0.94 |
| 500 | 488 | 488 | 0 | 0.20 | 0.40 | 1.63 |
| 1,000 | 957 | 957 | 0 | 0.33 | 0.35 | 3.28 |


## Running

```bash
pytest -q
pytest --cov=app --cov-report=term
PAYROLL_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost/payroll_test pytest -q
ruff check . && mypy
python -m scripts.benchmark --db postgresql+psycopg://user:pass@localhost/payroll_test
```
