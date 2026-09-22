# Security

Payroll data is sensitive personal and financial data. Controls in this prototype:

| Area | Control |
|---|---|
| Secrets | Only from environment (`PAYROLL_SECRET_KEY`, `PAYROLL_DEMO_PASSWORD`, DB URL) or an untracked `.env`. Production refuses to start without a secret key; dev uses an ephemeral key. `.env` is git- and docker-ignored. No passwords or keys are in the code. |
| Passwords | bcrypt (cost 12), minimum 10 characters; login failures are audited without the attempted password. |
| Sessions | JWT (HS256) with expiry (default 60 min). Streamlit sessions are server-side. |
| Authorisation | Role → permission matrix (`app/core/security.py`); every API route declares its permission; the UI only shows pages the role may use and re-checks inside each page. |
| Segregation of duties | CRITICAL exceptions cannot be acknowledged; approval blocked while ERROR/CRITICAL are open; in `PAYROLL_ENV=production` the approver must differ from the run creator (four-eyes). |
| PII minimisation | PPSN masked (`•••••23T`) in every list, register, payslip, export and audit value; full IBAN never stored (masked placeholder only). |
| Logging | A logging filter redacts PPSN-shaped strings and `password=` / `token=` / `secret=` values. |
| Audit | Employee create/update (salary changes separately), tax-profile/RPN changes, calculations, recalculations, approvals, reversals (with reason), exception resolutions, rule changes (with reason), payslip generation, submission preparation, logins. |
| Data integrity | FK, unique and CHECK constraints (status, severity, non-negative amounts); Pydantic validation on all API input; locked runs cannot be recalculated. |
| Rules | Only VERIFIED rules can be used; changing verification status requires a reason and is audited. |

## Roles

| Permission | Payroll Admin | Payroll Analyst | HR Admin | Finance Manager | System Admin |
|---|:-:|:-:|:-:|:-:|:-:|
| employee read / write | ✅ / ✅ | ✅ / – | ✅ / ✅ | – | ✅ / – |
| tax profile / RPN write | ✅ | – | – | – | – |
| payroll run / approve | ✅ / ✅ | – | – | – | – |
| payroll read, reports | ✅ | ✅ | – | ✅ | – |
| analytics | ✅ | ✅ | – | ✅ | – |
| rules read / write | ✅ / – | ✅ / – | – | ✅ / – | ✅ / ✅ |
| Revenue prep | ✅ | – | – | – | – |
| audit read | ✅ | – | – | – | ✅ |
| users, company config | – | – | – | – | ✅ |

## Not done (production hardening backlog)

TLS termination and security headers (reverse proxy), MFA/SSO, account lockout and rate limiting, encryption at
rest for PPSN columns, PostgreSQL row-level security per company, refresh-token rotation, secrets manager, DPIA and
GDPR retention schedule.
