# Limitations

This is a **portfolio prototype**. It demonstrates payroll knowledge and engineering practice; it is not certified
payroll software and must not be used to pay real people or make returns to Revenue.

## Compliance scope

* **No Revenue connectivity.** RPNs are imported from CSV; submissions are prepared and exported, never transmitted.
  Field names are not validated against Revenue's schema. See [REVENUE_INTEGRATION.md](REVENUE_INTEGRATION.md).
* **Blocked by design (no verified rule):** fortnightly emergency basis; any 2025 payroll needing PRSI; any 2027 pay date.
* **Monthly PRSI credit.** SW14 confirms the 52/12 scaling for thresholds; applying it to the €12 weekly credit
  (max €52/month, taper from €1,525.38) is an interpretation. Monthly payroll for employees earning €1,525–€1,837 a
  month should be checked against DSP guidance before relying on it.
* **Insurable weeks** default to 1 / 2 / 4 by frequency (can be overridden per input); 5-week months are not derived
  automatically.
* **Not implemented:** week 53, multiple employments with the same employer, share-based remuneration, PHB/income
  continuance, illness benefit and parental leave adjustments, termination/lump-sum rules, director (Class S) non-PAYE
  contributions, the €1,905 BIK threshold rule, USC surcharges, preferential loan and accommodation valuations (the
  "other" BIK valuer accepts an externally valued cash equivalent), salary sacrifice, the tax relief at source
  mechanics for medical insurance (the employee's credit arrives on the RPN), auto-enrolment (My Future Fund)
  contributions, bank/SEPA payment files.
* **USC exemption and reduced rate** are taken from the RPN only; the engine never self-assesses eligibility (a
  validation warning flags reduced status with salary > €60,000).
* **Pension relief limit** is tested on annualised current earnings each period — an approximation of the annual test.
* **Leavers/joiners** pro-rate basic salary by calendar days in the period; real employers may use working days.
* Revenue does not publish a full 2026 PAYE/USC worked example on the pages checked; PAYE/USC tests are derived by hand
  from published bands and cross-checked against full-year liability.

## Engineering scope

* The Docker/compose stack was written but not run in the build environment (container registry unreachable); the
  equivalent steps were verified directly on PostgreSQL 16.
* Streamlit is the MVP front end; it calls the service layer in-process. A production UI would sit on the REST API.
* Single-company UI (API supports multiple companies). No multi-tenant isolation at database level.
* Synthetic data: names, PPSNs (random but checksum-valid), employer number and company are fictitious.
* Budgets for variance analysis are synthetic (salary cost × 1.16).
