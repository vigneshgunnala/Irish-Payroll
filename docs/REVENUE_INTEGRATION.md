# Revenue integration

## What is implemented

**Submission preparation only.** `app/services/revenue.py` builds, validates and exports, per approved run:

* **Header** — employer registration number, tax year, pay date, submission ID, run reference, pay frequency, line count.
* **One line per employee** — PPSN and employment ID, name, RPN number, tax basis, gross pay, pay for income tax,
  income tax paid (refunds negative), pay for employee/employer PRSI, PRSI class/subclass and insurable weeks,
  employee and employer PRSI, pay for USC, USC status, USC paid, LPT deducted, taxable benefits, employee pension.

These are the pay details Revenue lists for a payroll submission
([What employee pay details do you include?](https://www.revenue.ie/en/employing-people/becoming-an-employer-and-ongoing-obligations/information-on-payroll-submission/what-employee-pay-details-do-you-include.aspx)).
Field **names** are modelled on that list; they have **not** been validated against Revenue's official API schema.

Validation before export: employer number present; PPSN checksum; PPSN missing (warning — only allowed on the emergency
basis); employment ID present; RPN number required unless the employee is on the emergency basis.
A submission with blocking errors is stored as `VALIDATION_FAILED`; otherwise `PREPARED`, and the run moves to `SUBMITTED`
(meaning *"submission data prepared and handed off"*, not *"accepted by Revenue"*).

RPNs are imported from CSV (`/rpn/import`, UI → RPN / Tax Data), with per-line validation, history in `rpn_records`
and an audited update of the employee's tax profile.

## What is NOT implemented (deliberately)

No data is transmitted to Revenue and no RPN is fetched from Revenue. A real integration needs:

1. Revenue's PAYE Modernisation web-service specification and schemas (REST/JSON) for RPN look-up and payroll submission.
2. A ROS digital certificate for the employer or agent, and message signing as specified by Revenue.
3. Handling of asynchronous submission status, validation responses, corrections, and the monthly statement.
4. Revenue's software-developer testing process before live use.

None of those were verified in this build, so the system does not claim them.

## Integration seam

```python
class RevenueGateway(ABC):
    def submit(self, submission: RevenueSubmission) -> dict: ...
    def fetch_rpns(self, employer_reg: str, tax_year: int) -> list[dict]: ...
```

`NotConfiguredGateway` raises `NotImplementedError` with a clear message. A certified client would implement this
interface; nothing in the engine, rules or workflow would change. `RevenueSubmission.payload` and `validation_errors`
are already stored so responses can be reconciled against what was sent.
