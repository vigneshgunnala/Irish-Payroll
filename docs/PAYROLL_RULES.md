# Payroll rules (2026) — values and sources

Every statutory value used by the engine is listed below exactly as stored in [`app/rules/data`](../app/rules/data).
Values were checked against the linked official page/document on **21–22 September 2026**. The engine refuses any rule
whose status is not `VERIFIED` (`RuleRepository.get` raises `UnverifiedRuleError` → the employee's result is
`UNVERIFIED` and a CRITICAL exception is raised).

## Primary sources

| Key | Authority | Document |
|---|---|---|
| Tax relief charts | Revenue | https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx |
| Budget 2026 summary | Revenue | https://www.revenue.ie/en/corporate/press-office/budget-information/current-year/budget-summary.pdf |
| USC standard rates | Revenue | https://www.revenue.ie/en/jobs-and-pensions/usc/standard-rates-thresholds.aspx |
| USC reduced rates | Revenue | https://www.revenue.ie/en/jobs-and-pensions/usc/reduced-rates.aspx |
| Emergency basis tables (2022–2026) | Revenue | https://www.revenue.ie/en/jobs-and-pensions/documents/emergency-rates.pdf |
| Emergency basis rules | Revenue | https://www.revenue.ie/en/employing-people/paying-an-employee/methods-of-calculating-tax/emergency-basis.aspx |
| SW14 PRSI Contribution Rates & User Guide, Jan 2026 | DSP | https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf |
| Advance Notice for 2026 – PRSI | DSP | https://assets.gov.ie/static/documents/b9146265/20251008_Advance_Notice_2026_Final.pdf |
| Employers' Guide to PAYE (TDM 42-04-35A) | Revenue | https://www.revenue.ie/en/tax-professionals/tdm/income-tax-capital-gains-tax-corporation-tax/part-42/42-04-35a.pdf |
| LPT deduction | Revenue | https://www.revenue.ie/en/employing-people/paying-your-employees-tax-to-revenue/deduction-of-lpt.aspx |
| Pension relief / limits | Revenue | https://www.revenue.ie/en/jobs-and-pensions/pension/relief/tax-relief-limits.aspx |
| Company car BIK | Revenue | https://www.revenue.ie/en/employing-people/benefit-in-kind-for-employers/private-use-company-cars/calculate-value-benefit.aspx |
| Medical insurance BIK | Revenue | https://www.revenue.ie/en/employing-people/benefit-in-kind-for-employers/valuation-of-benefits/payment-medical-insurance-employees.aspx |
| Small benefit exemption | Revenue | https://www.revenue.ie/en/employing-people/benefit-in-kind-for-employers/valuation-of-benefits/small-benefit-exemption.aspx |

## Headline 2026 figures

| Item | 2026 value |
|---|---|
| Income tax | 20% standard rate, 40% higher rate; single SRCOP €44,000 (one parent €48,000; married one income €53,000; two incomes up to +€35,000) — per-employee figures come from the RPN |
| Main credits (reference) | Personal €2,000 single / €4,000 married; Employee (PAYE) €2,000 |
| Emergency (PPSN held) | Weekly cut-off €846.16 in weeks 1–4, then €0; monthly €3,666.67 in month 1, then €0; no credits; USC 8% on all pay |
| Emergency (no PPSN) | All pay at 40%, no credits; USC 8% |
| USC | 0.5% to €12,012 · 2% to €28,700 · 3% to €70,044 · 8% balance; exempt if total income ≤ €13,000 (per RPN); reduced 0.5%/2% for 70+ or full medical card with income ≤ €60,000 (per RPN) |
| PRSI Class A 1 Jan–30 Sep 2026 | A0 €38–€352 nil/9.00% · AX €352.01–€424 4.20%/9.00% · AL €424.01–€552 4.20%/9.00% · A1 >€552 4.20%/11.25%; tapered credit max €12/week (reduced by 1/6 of earnings over €352.01) |
| PRSI Class A from 1 Oct 2026 | Employee 4.35%; employer 9.15% (≤ €552) / 11.40% (> €552); credit unchanged |
| Pension relief | 15% (<30), 20% (30–39), 25% (40–49), 30% (50–54), 35% (55–59), 40% (60+) of earnings capped at €115,000; no USC or PRSI relief |
| Company car BIK | OMV less €10,000 (A1–D) in 2026, plus €20,000 extra for A1 (EV); % of reduced OMV by CO₂ category and business km (15%–37.5% at ≤26,000 km, falling in three bands) |
| Medical insurance BIK | Gross premium (before tax relief at source) |
| Small benefit exemption | Up to 5 non-cash benefits, €1,500 combined per year (from 2025) |
| LPT | Only the amount on the RPN, spread equally over the year |

## Interpretation notes (documented, not hidden)

* **Period conversion for PRSI.** Weekly thresholds are scaled by 52/12 for monthly pay. Evidence: SW14's monthly bands
  (A0 "€165* to €1,525", AX to €1,837, AL to €2,392) equal the weekly limits × 52/12. SW14 only shows the €12 credit
  weekly, so applying the same factor to the credit (max €52/month) is an interpretation — flagged in LIMITATIONS.md.
* **Periodised cut-offs/credits are rounded up to the cent**, matching Revenue's published €846.16 weekly emergency
  cut-off (44,000 ÷ 52 = 846.1538).
* **Class B/C/D** employee PRSI: lower rate on pay up to €1,443/week and the higher rate on the balance above it,
  exactly as laid out in the DSP table.

## Verification history — how the gate worked in practice

| Date | Rules | Event |
|---|---|---|
| 21 Sep 2026 | `PRSI-2026-J-H2`, `-B-H2`, `-C-H2`, `-D-H2` (1 Oct 2026 rates for Classes J, B, C, D) | Only found in a payroll vendor's knowledge base (DSP had only said "all PRSI rates will increase by a further 0.15%"). Stored **UNVERIFIED** → any October payroll touching those classes was **blocked** (e.g. over-66 Class J employees in the October demo run raised CRITICAL exceptions). |
| 22 Sep 2026 | same four rules | Located the per-class "From 1 October 2026" rows in DSP's **SW14 (January 2026)**; values matched. Rules re-sourced to SW14, status set to **VERIFIED**; the rule sync recorded a `RULE_CHANGED` audit entry in each database. |

Still blocked in code because no verified rule exists: the fortnightly emergency basis; any 2025 payroll that needs
PRSI (2025 PRSI was not re-verified); any pay date in 2027. Tests prove an UNVERIFIED rule blocks calculation.

## All rules

| Rule ID | Category.parameter | Value | Effective | Status | Source |
|---|---|---|---|---|---|
| `PAYE-2025-RATE-HIGH` | PAYE.higher_rate | `0.40` | 2025-01-01 → 2025-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx) |
| `PAYE-2025-PERIOD-ROUNDING` | PAYE.period_amount_rounding | `ROUND_UP_CENT` | 2025-01-01 → 2025-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/documents/emergency-rates.pdf) |
| `PAYE-2025-RATE-STD` | PAYE.standard_rate | `0.20` | 2025-01-01 → 2025-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx) |
| `USC-2025-BANDS` | USC.standard_bands | `[{"upper": "12012", "rate": "0.005"}, {"upper": "27382", "rate": "0…` | 2025-01-01 → 2025-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/usc/standard-rates-thresholds.aspx) |
| `BIK-2026-CAR-PERCENTAGES` | BIK.car_business_km_percentages | `[{"max_km": 26000, "A1": "0.15", "A": "0.225", "B": "0.2625", "C": …` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/employing-people/benefit-in-kind-for-employers/private-use-company-cars/calculate-value-benefit.aspx) |
| `BIK-2026-CAR-CATEGORIES` | BIK.car_co2_categories | `[{"code": "A1", "max_co2": "0"}, {"code": "A", "max_co2": "59"}, {"…` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/employing-people/benefit-in-kind-for-employers/private-use-company-cars/calculate-value-benefit.aspx) |
| `BIK-2026-CAR-EV-REDUCTION` | BIK.car_ev_additional_reduction | `20000` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/employing-people/benefit-in-kind-for-employers/private-use-company-cars/calculate-value-benefit.aspx) |
| `BIK-2026-CAR-OMV-REDUCTION` | BIK.car_omv_reduction | `{"A1": "10000", "A": "10000", "B": "10000", "C": "10000", "D": "100…` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/employing-people/benefit-in-kind-for-employers/private-use-company-cars/calculate-value-benefit.aspx) |
| `BIK-2026-MEDICAL` | BIK.medical_insurance_valuation | `GROSS_PREMIUM` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/employing-people/benefit-in-kind-for-employers/valuation-of-benefits/payment-medical-insurance-employees.aspx) |
| `BIK-2026-NOTIONAL-PAY` | BIK.notional_pay_treatment | `{"paye": true, "usc": true, "prsi": true}` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/tax-professionals/tdm/income-tax-capital-gains-tax-corporation-tax/part-42/42-04-35a.pdf) |
| `BIK-2026-SMALL-BENEFIT` | BIK.small_benefit_exemption | `{"max_value": "1500", "max_count": 5}` | 2025-01-01 → open | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/employing-people/benefit-in-kind-for-employers/valuation-of-benefits/small-benefit-exemption.aspx) |
| `EMRG-2026-SRCOP-MONTHLY` | EMERGENCY.srcop_monthly_month_1 | `3666.67` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/documents/emergency-rates.pdf) |
| `EMRG-2026-SRCOP-WEEKLY` | EMERGENCY.srcop_weekly_weeks_1_4 | `846.16` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/documents/emergency-rates.pdf) |
| `EMRG-2026-SRCOP-WEEKS` | EMERGENCY.srcop_weekly_weeks_count | `4` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/employing-people/paying-an-employee/methods-of-calculating-tax/emergency-basis.aspx) |
| `EMRG-2026-CREDITS` | EMERGENCY.tax_credits | `0` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/documents/emergency-rates.pdf) |
| `EMRG-2026-USC-RATE` | EMERGENCY.usc_rate | `0.08` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/documents/emergency-rates.pdf) |
| `LPT-2026-METHOD` | LPT.deduction_method | `EQUAL_SPREAD_FROM_RPN` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/employing-people/paying-your-employees-tax-to-revenue/deduction-of-lpt.aspx) |
| `PAYE-2026-CREDIT-EMPLOYEE` | PAYE.credit_employee | `2000` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx) |
| `PAYE-2026-CREDIT-PERSONAL-MARRIED` | PAYE.credit_personal_married | `4000` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx) |
| `PAYE-2026-CREDIT-PERSONAL-SINGLE` | PAYE.credit_personal_single | `2000` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx) |
| `PAYE-2026-RATE-HIGH` | PAYE.higher_rate | `0.40` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx) |
| `PAYE-2026-PERIOD-ROUNDING` | PAYE.period_amount_rounding | `ROUND_UP_CENT` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/documents/emergency-rates.pdf) |
| `PAYE-2026-SRCOP-MARRIED1` | PAYE.srcop_married_one_income | `53000` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx) |
| `PAYE-2026-SRCOP-MARRIED2-INC` | PAYE.srcop_married_two_income_max_increase | `35000` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx) |
| `PAYE-2026-SRCOP-ONEPARENT` | PAYE.srcop_one_parent | `48000` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx) |
| `PAYE-2026-SRCOP-SINGLE` | PAYE.srcop_single | `44000` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx) |
| `PAYE-2026-RATE-STD` | PAYE.standard_rate | `0.20` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/personal-tax-credits-reliefs-and-exemptions/tax-relief-charts/index.aspx) |
| `PEN-2026-AGE-LIMITS` | PENSION.age_related_limits | `[{"min_age": 0, "percent": "0.15"}, {"min_age": 30, "percent": "0.2…` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/pension/relief/tax-relief-limits.aspx) |
| `PEN-2026-EARNINGS-CAP` | PENSION.earnings_cap | `115000` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/pension/relief/tax-relief-limits.aspx) |
| `PEN-2026-TREATMENT` | PENSION.employee_contribution_treatment | `{"OCCUPATIONAL": {"relieve_paye": true, "relieve_usc": false, "reli…` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/tax-professionals/tdm/income-tax-capital-gains-tax-corporation-tax/part-42/42-04-35a.pdf) |
| `PRSI-2026-A-H1` | PRSI.class_A | `{"class_j_below_weekly": "38", "employee_exempt_up_to_weekly": "352…` | 2026-01-01 → 2026-09-30 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf) |
| `PRSI-2026-A-H2` | PRSI.class_A | `{"class_j_below_weekly": "38", "employee_exempt_up_to_weekly": "352…` | 2026-10-01 → 2026-12-31 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf) |
| `PRSI-2026-B-H1` | PRSI.class_B | `{"employee_exempt_up_to_weekly": "352", "employee_lower_rate": "0.0…` | 2026-01-01 → 2026-09-30 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/b9146265/20251008_Advance_Notice_2026_Final.pdf) |
| `PRSI-2026-B-H2` | PRSI.class_B | `{"employee_exempt_up_to_weekly": "352", "employee_lower_rate": "0.0…` | 2026-10-01 → 2026-12-31 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf) |
| `PRSI-2026-C-H1` | PRSI.class_C | `{"employee_exempt_up_to_weekly": "352", "employee_lower_rate": "0.0…` | 2026-01-01 → 2026-09-30 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/b9146265/20251008_Advance_Notice_2026_Final.pdf) |
| `PRSI-2026-C-H2` | PRSI.class_C | `{"employee_exempt_up_to_weekly": "352", "employee_lower_rate": "0.0…` | 2026-10-01 → 2026-12-31 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf) |
| `PRSI-2026-D-H1` | PRSI.class_D | `{"employee_exempt_up_to_weekly": "352", "employee_lower_rate": "0.0…` | 2026-01-01 → 2026-09-30 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/b9146265/20251008_Advance_Notice_2026_Final.pdf) |
| `PRSI-2026-D-H2` | PRSI.class_D | `{"employee_exempt_up_to_weekly": "352", "employee_lower_rate": "0.0…` | 2026-10-01 → 2026-12-31 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf) |
| `PRSI-2026-H-H1` | PRSI.class_H | `{"employee_exempt_up_to_weekly": "352", "employee_rate": "0.041", "…` | 2026-01-01 → 2026-09-30 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/b9146265/20251008_Advance_Notice_2026_Final.pdf) |
| `PRSI-2026-H-H2` | PRSI.class_H | `{"employee_exempt_up_to_weekly": "352", "employee_rate": "0.0425", …` | 2026-10-01 → 2026-12-31 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf) |
| `PRSI-2026-J-H1` | PRSI.class_J | `{"employee_rate": "0", "employer_rate": "0.007", "subclasses": [{"c…` | 2026-01-01 → 2026-09-30 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/b9146265/20251008_Advance_Notice_2026_Final.pdf) |
| `PRSI-2026-J-H2` | PRSI.class_J | `{"employee_rate": "0", "employer_rate": "0.0085", "subclasses": [{"…` | 2026-10-01 → 2026-12-31 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf) |
| `PRSI-2026-K-H1` | PRSI.class_K | `{"employee_rate": "0.042", "employer_rate": "0", "employee_exempt_u…` | 2026-01-01 → 2026-09-30 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf) |
| `PRSI-2026-K-H2` | PRSI.class_K | `{"employee_rate": "0.0435", "employer_rate": "0", "employee_exempt_…` | 2026-10-01 → 2026-12-31 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf) |
| `PRSI-2026-M` | PRSI.class_M | `{"employee_rate": "0", "employer_rate": "0", "subclasses": [{"code"…` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/b9146265/20251008_Advance_Notice_2026_Final.pdf) |
| `PRSI-2026-S-H1` | PRSI.class_S | `{"employee_rate": "0.042", "employer_rate": "0", "subclasses": [{"c…` | 2026-01-01 → 2026-09-30 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/b9146265/20251008_Advance_Notice_2026_Final.pdf) |
| `PRSI-2026-S-H2` | PRSI.class_S | `{"employee_rate": "0.0435", "employer_rate": "0", "subclasses": [{"…` | 2026-10-01 → 2026-12-31 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf) |
| `PRSI-2026-PERIOD-CONVERSION` | PRSI.weeks_per_period | `{"WEEKLY": "1", "FORTNIGHTLY": "2", "MONTHLY": "4.333333333333"}` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Department of Social Protection](https://assets.gov.ie/static/documents/cb168977/PRSI_C20260116_Contribution_Rates_and_User_Guide_-_SW_14_-_English_Version_-_January_2026_.pdf-web.pdf) |
| `USC-2026-EXEMPT-THRESHOLD` | USC.exemption_threshold | `13000` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/usc/index.aspx) |
| `USC-2026-REDUCED-BANDS` | USC.reduced_bands | `[{"upper": "12012", "rate": "0.005"}, {"upper": null, "rate": "0.02"}]` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/usc/reduced-rates.aspx) |
| `USC-2026-REDUCED-LIMIT` | USC.reduced_income_limit | `60000` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/usc/reduced-rates.aspx) |
| `USC-2026-BANDS` | USC.standard_bands | `[{"upper": "12012", "rate": "0.005"}, {"upper": "28700", "rate": "0…` | 2026-01-01 → 2026-12-31 | ✅ VERIFIED | [Revenue Commissioners](https://www.revenue.ie/en/jobs-and-pensions/usc/standard-rates-thresholds.aspx) |
