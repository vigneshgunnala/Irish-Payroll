"""Employees, employee profile, RPN / tax data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.security import Perm, mask_ppsn
from app.db.models import Department, Employee, PayrollResultRecord, PayrollRun, RpnRecord
from app.services.employees import create_employee, import_rpn_csv, update_employee, validate_ppsn
from ui.common import SERIES, can, company_id, current_user_obj, db, eur, guard, kpi, page_header, style_fig


def _employees(s) -> list[Employee]:
    return list(s.scalars(select(Employee).where(Employee.company_id == company_id())
                          .options(selectinload(Employee.department), selectinload(Employee.tax_profile))
                          .order_by(Employee.employee_number)))


def employees() -> None:
    guard(Perm.EMPLOYEE_READ)
    page_header("Employees", "Employee master data · PPSNs are masked in all list views")
    with db() as s:
        emps = _employees(s)
        depts = {d.department_id: d.name for d in s.scalars(select(Department).where(Department.company_id == company_id()))}
    df = pd.DataFrame([{
        "ID": e.employee_id, "Emp no.": e.employee_number, "Name": e.full_name, "PPSN": mask_ppsn(e.ppsn),
        "Department": e.department.name if e.department else "—", "Job title": e.job_title, "Frequency": e.pay_frequency.title(),
        "Pay": float(e.annual_salary) if e.salary_type == "SALARY" else float(e.hourly_rate or 0),
        "Pay basis": "Annual" if e.salary_type == "SALARY" else "Hourly", "PRSI": e.prsi_class or "⚠️ missing",
        "RPN": "✅" if e.tax_profile and e.tax_profile.rpn_number else "❌ none", "Pension": e.pension_scheme or "—",
        "Status": e.employment_status, "Start": e.employment_start_date} for e in emps])
    c = st.columns([2, 1.2, 1, 1, 1])
    q = c[0].text_input("Search name / employee number")
    dsel = c[1].multiselect("Department", sorted(set(depts.values())))
    fsel = c[2].multiselect("Frequency", ["Monthly", "Weekly"])
    ssel = c[3].multiselect("Status", ["ACTIVE", "LEFT"], default=["ACTIVE"])
    rpn_only = c[4].checkbox("Missing RPN only")
    v = df
    if q:
        v = v[v["Name"].str.contains(q, case=False) | v["Emp no."].str.contains(q, case=False)]
    if dsel:
        v = v[v["Department"].isin(dsel)]
    if fsel:
        v = v[v["Frequency"].isin(fsel)]
    if ssel:
        v = v[v["Status"].isin(ssel)]
    if rpn_only:
        v = v[v["RPN"] != "✅"]
    m = st.columns(4)
    kpi(m[0], "Employees shown", str(len(v)))
    kpi(m[1], "Active", str((df["Status"] == "ACTIVE").sum()))
    kpi(m[2], "Without RPN", str((df["RPN"] != "✅").sum()))
    kpi(m[3], "Departments", str(df["Department"].nunique()))
    sel = st.dataframe(v, hide_index=True, use_container_width=True, height=420, on_select="rerun", selection_mode="single-row",
                       column_config={"Pay": st.column_config.NumberColumn(format="€%.2f"), "ID": None})
    if sel and sel.selection.rows:
        st.session_state.employee_id = int(v.iloc[sel.selection.rows[0]]["ID"])
        st.info(f"Selected {v.iloc[sel.selection.rows[0]]['Name']} — open **Employee Profile** in the sidebar.")
    st.download_button("⬇️ Export (CSV, masked)", v.to_csv(index=False), "employees.csv", "text/csv")

    if can(Perm.EMPLOYEE_WRITE):
        with st.expander("➕ Add employee"):
            with st.form("add_emp"):
                c = st.columns(3)
                num = c[0].text_input("Employee number")
                fn = c[1].text_input("First name")
                ln = c[2].text_input("Last name")
                c = st.columns(3)
                ppsn = c[0].text_input("PPSN (optional)")
                dob = c[1].date_input("Date of birth", date(1990, 1, 1), min_value=date(1940, 1, 1))
                start = c[2].date_input("Start date", date.today())
                c = st.columns(3)
                dept = c[0].selectbox("Department", list(depts), format_func=depts.get)
                freq = c[1].selectbox("Pay frequency", ["MONTHLY", "WEEKLY"])
                prsi = c[2].selectbox("PRSI class", ["A", "S", "J", "H", "B", "C", "D", "K", "M"])
                c = st.columns(3)
                stype = c[0].selectbox("Salary type", ["SALARY", "HOURLY"])
                sal = c[1].number_input("Annual salary / hourly rate", min_value=0.0, value=40000.0)
                hours = c[2].number_input("Standard weekly hours (hourly)", 0.0, 80.0, 39.0)
                title = st.text_input("Job title")
                if st.form_submit_button("Create employee", type="primary"):
                    try:
                        with db() as s:
                            data = dict(company_id=company_id(), employee_number=num, first_name=fn, last_name=ln, ppsn=ppsn or None,
                                        date_of_birth=dob, employment_start_date=start, department_id=dept, pay_frequency=freq,
                                        prsi_class=prsi, salary_type=stype, job_title=title,
                                        employment_id=num)
                            if stype == "SALARY":
                                data["annual_salary"] = Decimal(str(sal))
                            else:
                                data.update(hourly_rate=Decimal(str(sal)), standard_hours=Decimal(str(hours)))
                            e = create_employee(s, current_user_obj(s), data)
                            st.session_state.employee_id = e.employee_id
                        st.success("Employee created. Without an RPN they will be taxed on the emergency basis.")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Could not create employee: {exc}")


def employee_profile() -> None:
    guard(Perm.EMPLOYEE_READ)
    with db() as s:
        emps = _employees(s)
        ids = [e.employee_id for e in emps]
        cur = st.session_state.get("employee_id", ids[0])
        eid = st.selectbox("Employee", ids, index=ids.index(cur) if cur in ids else 0,
                           format_func=lambda i: next(f"{e.employee_number} · {e.full_name}" for e in emps if e.employee_id == i))
        st.session_state.employee_id = eid
        e = next(x for x in emps if x.employee_id == eid)
        page_header(e.full_name, f"{e.employee_number} · {e.job_title or ''} · {e.department.name if e.department else 'No department'}")
        tp = e.tax_profile
        c = st.columns(4)
        kpi(c[0], "Pay", eur(e.annual_salary, 0) + " p.a." if e.salary_type == "SALARY" else f"{eur(e.hourly_rate)}/h × {e.standard_hours}h")
        kpi(c[1], "PRSI class", e.prsi_class or "⚠️ missing")
        kpi(c[2], "Tax basis (RPN)", tp.tax_basis if tp and tp.rpn_number else "EMERGENCY (no RPN)")
        kpi(c[3], "USC status", tp.usc_status if tp and tp.usc_status else "—")

        t1, t2, t3, t4 = st.tabs(["Details", "Tax profile / RPN", "Pay history", "Benefits"])
        with t1:
            ok, why = validate_ppsn(e.ppsn)
            st.markdown(f"""
| | | | |
|---|---|---|---|
| PPSN | {mask_ppsn(e.ppsn)} ({'valid' if ok else why}) | Date of birth | {e.date_of_birth} |
| Employment start | {e.employment_start_date} | Employment end | {e.employment_end_date or '—'} |
| Status | {e.employment_status} | Contract | {e.contract_type or '—'} |
| Pay frequency | {e.pay_frequency.title()} | Location | {e.location or '—'} |
| Pension | {e.pension_scheme or '—'} {f"(EE {Decimal(e.pension_ee_percent)*100:.1f}% / ER {Decimal(e.pension_er_percent)*100:.1f}%)" if e.pension_scheme else ''} | Employment ID | {e.employment_id or '—'} |
| Bank (placeholder) | {e.bank_iban_masked or '—'} | | |
""")
            if can(Perm.EMPLOYEE_WRITE):
                with st.form("edit_emp"):
                    st.markdown("**Change employee data** (audited)")
                    c = st.columns(4)
                    sal = c[0].number_input("Annual salary", value=float(e.annual_salary or 0), step=500.0, disabled=e.salary_type != "SALARY")
                    rate = c[1].number_input("Hourly rate", value=float(e.hourly_rate or 0), step=0.25, disabled=e.salary_type != "HOURLY")
                    prsi = c[2].text_input("PRSI class", value=e.prsi_class or "")
                    end = c[3].date_input("Employment end date", value=e.employment_end_date)
                    reason = st.text_input("Reason for change (required)")
                    if st.form_submit_button("Save changes", type="primary"):
                        if len(reason) < 5:
                            st.error("Please give a reason (≥5 characters).")
                        else:
                            ch = {"prsi_class": prsi.upper() or None, "employment_end_date": end,
                                  "employment_status": "LEFT" if end else "ACTIVE"}
                            if e.salary_type == "SALARY":
                                ch["annual_salary"] = Decimal(str(sal)).quantize(Decimal("0.01"))
                            else:
                                ch["hourly_rate"] = Decimal(str(rate)).quantize(Decimal("0.0001"))
                            update_employee(s, current_user_obj(s), e, ch, reason)
                            st.success("Saved. Recalculate any open payroll run to apply.")
        with t2:
            if tp is None or not tp.rpn_number:
                st.warning("No RPN held. The engine will apply the **emergency basis** and explain why in the calculation trace.")
            else:
                st.markdown(f"""
| RPN field | Value |
|---|---|
| RPN number | `{tp.rpn_number}` (effective {tp.rpn_effective_date}) |
| Tax basis | **{tp.tax_basis}** |
| Annual tax credits | {eur(tp.annual_tax_credits)} |
| Annual standard rate cut-off | {eur(tp.annual_srcop)} |
| USC status | {tp.usc_status} |
| LPT to deduct (annual) | {eur(tp.lpt_annual)} |
| Previous employment pay / tax (this year) | {eur(tp.prior_pay_for_tax)} / {eur(tp.prior_tax)} |
| Source / imported | {tp.rpn_source} · {tp.rpn_imported_at:%Y-%m-%d %H:%M} |
""")
            hist = s.scalars(select(RpnRecord).where(RpnRecord.employee_id == eid).order_by(RpnRecord.imported_at.desc())).all()
            if hist:
                st.caption("RPN history")
                st.dataframe(pd.DataFrame([{"RPN": h.rpn_number, "Effective": h.effective_date, "Basis": h.tax_basis,
                                            "Credits": float(h.annual_tax_credits), "SRCOP": float(h.annual_srcop), "USC": h.usc_status,
                                            "Imported": h.imported_at} for h in hist]), hide_index=True, use_container_width=True)
        with t3:
            rows = s.execute(select(PayrollResultRecord, PayrollRun).join(PayrollRun)
                             .where(PayrollResultRecord.employee_id == eid, PayrollRun.status != "REVERSED")
                             .order_by(PayrollRun.payment_date)).all()
            h = pd.DataFrame([{"Run": run.payroll_run_id, "Pay date": run.payment_date, "Period": run.payroll_period,
                               "Run status": run.status, "Gross": float(r.gross_pay), "PAYE": float(r.paye), "USC": float(r.usc),
                               "PRSI": float(r.prsi_ee), "Net": float(r.net_pay), "Basis": r.tax_basis_applied,
                               "Result": r.status} for r, run in rows])
            if h.empty:
                st.info("No payroll history.")
            else:
                fig = go.Figure()
                for i, col in enumerate(["Gross", "Net"]):
                    fig.add_scatter(x=h["Pay date"], y=h[col], name=col, mode="lines+markers", line=dict(width=2, color=SERIES[i]),
                                    marker=dict(size=8))
                fig.update_layout(yaxis_tickprefix="€", hovermode="x unified")
                st.plotly_chart(style_fig(fig, 280, "Gross and net pay by pay date"), use_container_width=True, theme=None)
                st.dataframe(h, hide_index=True, use_container_width=True,
                             column_config={c: st.column_config.NumberColumn(format="€%.2f") for c in ("Gross", "PAYE", "USC", "PRSI", "Net")})
        with t4:
            if not e.benefits:
                st.info("No benefits in kind configured.")
            for b in e.benefits:
                st.markdown(f"- **{b.benefit_type.replace('_', ' ').title()}** — {b.description or ''} "
                            + (f"(OMV {eur(b.omv, 0)}, {b.co2_g_km} g/km, {b.business_km:,} business km)" if b.benefit_type == "COMPANY_CAR" else "")
                            + (f"(gross premium {eur(b.annual_value)})" if b.annual_value else ""))


def rpn() -> None:
    page_header("RPN / tax data", "Revenue Payroll Notifications are authoritative for credits, cut-off, USC status and LPT")
    tmpl = ("employee_number,rpn_number,tax_basis,annual_tax_credits,annual_srcop,usc_status,lpt_annual,prior_pay_for_tax,"
            "prior_tax,prior_usc_pay,prior_usc,effective_date\nE0001,RPN2026000012,CUMULATIVE,4000,44000,ORDINARY,315,0,0,0,0,2026-09-01\n")
    with db() as s:
        emps = _employees(s)
    df = pd.DataFrame([{"Emp no.": e.employee_number, "Name": e.full_name, "RPN": (e.tax_profile.rpn_number if e.tax_profile else None) or "—",
                        "Basis": e.tax_profile.tax_basis if e.tax_profile else "—",
                        "Credits": float(e.tax_profile.annual_tax_credits) if e.tax_profile and e.tax_profile.annual_tax_credits else None,
                        "SRCOP": float(e.tax_profile.annual_srcop) if e.tax_profile and e.tax_profile.annual_srcop else None,
                        "USC": e.tax_profile.usc_status if e.tax_profile else "—",
                        "LPT p.a.": float(e.tax_profile.lpt_annual) if e.tax_profile else 0.0} for e in emps])
    c = st.columns(4)
    kpi(c[0], "Employees with RPN", str((df["RPN"] != "—").sum()))
    kpi(c[1], "Without RPN (emergency)", str((df["RPN"] == "—").sum()))
    kpi(c[2], "Week 1 / Month 1", str((df["Basis"] == "WEEK1_MONTH1").sum()))
    kpi(c[3], "LPT instructions", str((df["LPT p.a."] > 0).sum()))
    st.dataframe(df, hide_index=True, use_container_width=True, height=360,
                 column_config={c: st.column_config.NumberColumn(format="€%.2f") for c in ("Credits", "SRCOP", "LPT p.a.")})
    if can(Perm.TAX_PROFILE_WRITE):
        st.markdown("#### Import RPN file")
        st.caption("Direct RPN retrieval from Revenue's API is not implemented (see REVENUE_INTEGRATION.md) — import a CSV extract.")
        st.download_button("⬇️ RPN CSV template", tmpl, "rpn_template.csv", "text/csv")
        up = st.file_uploader("RPN CSV", type="csv")
        if up and st.button("Import", type="primary"):
            try:
                with db() as s:
                    res = import_rpn_csv(s, current_user_obj(s), company_id(), up.getvalue().decode("utf-8-sig"), 2026)
                st.success(f"Imported {res['imported']} RPN(s).")
                if res["errors"]:
                    st.dataframe(pd.DataFrame(res["errors"]), hide_index=True)
            except ValueError as exc:
                st.error(str(exc))
