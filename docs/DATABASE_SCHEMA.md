# Database schema

PostgreSQL-first (JSONB for traces/payloads), portable to SQLite for the local demo. Created by Alembic
(`migrations/versions/*_initial_schema.py`, generated against PostgreSQL 16). 23 tables.

## ER diagram

```mermaid
erDiagram
  companies ||--o{ departments : has
  companies ||--o{ employees : employs
  companies ||--o{ payroll_runs : runs
  departments ||--o{ employees : "cost centre"
  employees ||--|| employee_tax_profiles : "current RPN position"
  employees ||--o{ rpn_records : "RPN history"
  employees ||--o{ employee_benefits : "BIK config"
  payroll_runs ||--o{ payroll_inputs : "variable inputs"
  payroll_inputs ||--o{ payroll_earnings : lines
  payroll_inputs ||--o{ payroll_deductions : "input deductions"
  payroll_runs ||--o{ payroll_results : "one per employee"
  payroll_results ||--o{ payroll_deductions : "calculated lines"
  payroll_results ||--o| payslips : renders
  payroll_runs ||--o{ payroll_exceptions : raises
  payroll_runs ||--o{ revenue_submissions : prepares
  payroll_runs |o--o| payroll_runs : "correction reverses"
  users }o--|| roles : has
  users ||--o{ payroll_audit_logs : acts

  employees {
    int employee_id PK
    string employee_number UK "per company"
    string ppsn "masked in all views"
    date employment_start_date
    date employment_end_date
    string salary_type "SALARY|HOURLY (check)"
    numeric annual_salary "check >= 0"
    string pay_frequency "WEEKLY|FORTNIGHTLY|MONTHLY"
    string prsi_class
    string pension_scheme
  }
  employee_tax_profiles {
    string tax_basis "CUMULATIVE|WEEK1_MONTH1|EMERGENCY"
    numeric annual_tax_credits
    numeric annual_srcop
    string usc_status "ORDINARY|REDUCED|EXEMPT"
    numeric lpt_annual
    numeric prior_pay_for_tax
    numeric prior_tax
    string rpn_number
  }
  payroll_runs {
    int payroll_run_id PK
    int tax_year
    int payroll_period
    date payment_date
    string frequency
    string status "8-state check"
    string run_type "REGULAR|CORRECTION"
    jsonb totals
  }
  payroll_results {
    numeric gross_pay
    numeric pay_for_tax
    numeric paye
    numeric usc
    numeric prsi_ee
    numeric prsi_er
    string prsi_subclass
    numeric lpt
    numeric net_pay
    numeric employer_cost
    jsonb ytd "snapshot after this period"
    jsonb trace "calculation steps + rule refs"
    jsonb rules_used
    string error_code
  }
  tax_rules {
    string rule_id PK
    string category
    string parameter
    jsonb value
    date effective_from
    date effective_to
    string source_url
    date verified_date
    string status "VERIFIED|UNVERIFIED|SUPERSEDED"
  }
```

## Tables

| Table | Purpose |
|---|---|
| `companies`, `departments` | Employer (registration number, frequency, financial year) and cost centres with monthly budgets |
| `employees` | Master data. Only a masked IBAN placeholder is stored — no full bank details in the MVP |
| `employee_tax_profiles` | Current RPN-derived position used by the engine (unique per employee) |
| `rpn_records` | Every imported RPN (history, raw row, import timestamp, source) |
| `employee_benefits` | Recurring BIK configuration valued each period |
| `payroll_runs` | Run header, status machine (CHECK constraint), totals JSON, timing |
| `payroll_inputs` / `payroll_earnings` | Variable inputs per employee per run (unique run+employee) |
| `payroll_deductions` | Input deductions (`input_id`) and calculated deduction lines (`result_id`); CHECK amount ≥ 0 |
| `payroll_results` | One row per employee per run: every pay base, deduction, employer figure, YTD snapshot, trace, rules used, error code |
| `payroll_exceptions` | ENGINE / VALIDATION / ANOMALY / RECONCILIATION items with severity CHECK and resolution |
| `payroll_audit_logs` | User, timestamp, action, entity, before/after (sanitised), reason |
| `payslips` | Rendered HTML per approved result |
| `revenue_submissions` | Prepared submission payload, validation errors, status |
| `tax_rules`, `usc_rules`, `prsi_rules`, `lpt_rules`, `pension_rules`, `bik_rules` | Identical rule columns per family (PAYE + emergency rules live in `tax_rules`) |
| `users`, `roles` | Hashed passwords, role codes and their permission lists |

## Integrity & indexes

* Unique: `(company_id, employee_number)`, `(payroll_run_id, employee_id)` on inputs and results, `(employee_id, rpn_number)`, `tax_registration_number`, `submission_ref`, user email.
* CHECK constraints: salary/rate ≥ 0, salary type, pay frequency, run status, exception severity, deduction amount ≥ 0.
* Foreign keys enforced on both PostgreSQL and SQLite (`PRAGMA foreign_keys=ON`).
* Indexes on all foreign keys, run status, `(company_id, tax_year, frequency, payroll_period)`, audit timestamp/action, rule `tax_year`/`rule_set_id`.
* The service layer additionally prevents two REGULAR runs for the same company/year/frequency/period.
