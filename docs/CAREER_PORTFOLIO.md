# Career portfolio notes

Target roles: **Payroll Administrator · Payroll Analyst · Payroll Specialist · Payroll Data Analyst · HR/Payroll Technology** (Ireland).

## One-line pitch

> I built an Irish payroll system that calculates PAYE, USC, PRSI, LPT, pension and BIK from versioned Revenue/DSP rules, runs 300 employees in under a second, blocks anything it can't verify, and can show exactly why any deduction is what it is.

## What to demo (10 minutes)

1. **Dashboard** — September payroll: employer cost, gross, net, statutory liability, trend and department cost.
2. **Exceptions** — the September run is blocked: a missing PRSI class (CRITICAL, cannot be acknowledged), a duplicated travel allowance and a 120-hour overtime claim (z-score outlier).
3. **Fix at source → recalculate → resolve → approve** — show that approval locks the run and generates payslips.
4. **Payroll Calculation** — pick an employee: gross-to-net waterfall, then open PAYE: cumulative pay, cumulative cut-off/credits, 20%/40% portions, tax already deducted → this period's PAYE, each step linked to its Revenue source.
5. **Tax Rules** — 52 rules with dates, sources and verification status; tell the story of the four Oct-2026 PRSI rules that were blocked as UNVERIFIED until confirmed in DSP's SW14 (then show that a System Admin can un-verify a rule and the next calculation is blocked).
6. **Create the October run** — the PRSI trace now cites `PRSI-2026-A-H2` (4.35% / 9.15% / 11.40%).
7. **Reports** — liabilities due to Revenue, balanced GL journal, Excel export; **Revenue Submission** — prepared, validated, masked export.

## Interview talking points

| Question | Where the project answers it |
|---|---|
| "How does cumulative tax work?" | New cumulative liability − tax already deducted; refunds happen automatically; tests prove a year of equal pay equals the annual liability to within cents. |
| "Employee says their tax is wrong." | Open the trace: RPN basis, credits, cut-off, cumulative figures, and the rule/source behind each rate. |
| "New starter with no RPN?" | Emergency basis, explained in the trace: PPSN held → €846.16/week for 4 weeks (or €3,666.67 month 1), then 40%, no credits, USC 8%. |
| "Pension and USC?" | Net pay arrangement relieves income tax only — pay for USC and PRSI still includes the contribution. |
| "What changes on 1 October 2026?" | Class A PRSI 4.2% → 4.35% employee, 9%/11.25% → 9.15%/11.40% employer; selected by pay date. |
| "How do you control a payroll?" | Validation severities, exception queue, reconciliation (employee lines = run totals = deduction lines), approval gates, locking, reversal/correction, audit log. |
| "How would you analyse payroll cost?" | Department cost vs budget and previous period, overtime/bonus outliers, gross/net distributions, effective deduction rate. |
| "Where would you not trust the system?" | LIMITATIONS.md — blocked cases, monthly PRSI credit interpretation, no Revenue connectivity. |

## CV bullets

* Built an Irish payroll prototype (Python, FastAPI, PostgreSQL, Streamlit) calculating PAYE, USC, PRSI (9 classes), LPT, pension relief and BIK from 52 versioned, source-cited 2026 Revenue/DSP rules; unverified rules are automatically blocked.
* Designed a traceable gross-to-net engine producing a step-by-step audit trail for every deduction; 110 automated tests (91% coverage) including DSP's published PRSI-credit example, passing on SQLite and PostgreSQL.
* Automated a 300-employee monthly run (< 1 s) with validation, statistical anomaly detection, three-way reconciliation, approval workflow, payslips (PDF/HTML), balanced GL journal and Revenue submission data preparation.
* Built payroll analytics (department cost vs budget, variance, overtime and bonus outliers, net-pay change detection) with pandas and Plotly.

## What I learned

See the README section **"What I learned"** — Irish payroll is RPN-driven; cumulative PAYE is a running reconciliation; USC/PRSI follow different bases from PAYE; rounding and effective dates are rules too; and a correct figure that can't be explained, reconciled and traced to an approver isn't payroll-ready.
