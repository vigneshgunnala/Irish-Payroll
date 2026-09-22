"""Reports, analytics, tax rules, Revenue submission, audit log, settings."""

from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from app.core.security import ROLE_PERMISSIONS, Perm, Role
from app.db.models import AuditLog, Company, PayrollRun, RevenueSubmission, User
from app.services import analytics as an
from app.services import reports as rp
from app.services.payroll_service import FINAL_STATUSES, mark_submitted
from app.services.revenue import export_json, prepare_submission
from app.services.rules_service import repository_from_db, set_rule_status
from ui.common import SERIES, can, company_id, current_user_obj, db, eur, guard, kpi, page_header, style_fig, user
from ui.views_payroll import _pick_run


def reports() -> None:
    guard(Perm.REPORTS)
    page_header("Reports", "Payroll register, statutory liabilities, GL journal and exports")
    with db() as s:
        run = _pick_run(s, "rep_run")
        if not run or not run.totals:
            st.info("Select a calculated run.")
            return
        reg = rp.register(s, run)
        liab = rp.liabilities(run)
        jr = rp.journal(run)
        wb = rp.run_workbook(s, run)
    t1, t2, t3 = st.tabs(["Summary & liabilities", "Payroll journal", "Payroll register"])
    with t1:
        c = st.columns(2)
        with c[0]:
            st.markdown("**Employee deductions vs employer liabilities**")
            t = run.totals
            st.table(pd.DataFrame([
                ["Gross pay", eur(t["gross_pay"])], ["− PAYE", eur(t["paye"])], ["− USC", eur(t["usc"])],
                ["− Employee PRSI", eur(t["prsi_ee"])], ["− LPT", eur(t["lpt"])], ["− Employee pension", eur(t["pension_ee"])],
                ["− Other deductions", eur(t["other_deductions"])], ["= Net pay", eur(t["net_pay"])],
                ["Employer PRSI (employer cost)", eur(t["prsi_er"])], ["Employer pension (employer cost)", eur(t["pension_er"])],
                ["Total employer cost", eur(t["employer_cost"])]], columns=["Line", "Amount"]).set_index("Line"))
        with c[1]:
            st.markdown("**Payroll statutory liability (due to Revenue)**")
            st.table(pd.DataFrame([[x["liability"], eur(x["amount"])] for x in liab], columns=["Liability", "Amount"]).set_index("Liability"))
    with t2:
        jdf = pd.DataFrame([{**x, "debit": float(x["debit"]), "credit": float(x["credit"])} for x in jr])
        st.dataframe(jdf, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="€%.2f") for c in ("debit", "credit")})
        bal = rp.journal_balanced(jr)
        st.markdown(("✅ Journal balances" if bal else "🛑 Journal does NOT balance") +
                    f" — debits {eur(jdf['debit'].sum())} / credits {eur(jdf['credit'].sum())}")
        st.download_button("⬇️ Journal CSV", jdf.to_csv(index=False), f"journal_run{run.payroll_run_id}.csv", "text/csv")
    with t3:
        st.dataframe(reg, hide_index=True, use_container_width=True, height=420)
    c = st.columns(3)
    c[0].download_button("⬇️ Excel workbook (summary, register, liabilities, journal)", wb, f"payroll_run{run.payroll_run_id}.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    c[1].download_button("⬇️ Register CSV", reg.to_csv(index=False), f"register_run{run.payroll_run_id}.csv", "text/csv")


def analytics() -> None:
    guard(Perm.ANALYTICS)
    page_header("Payroll analytics", "Cost, employee, department and variance analysis (monthly payroll)")
    with db() as s:
        df = an.results_frame(s, company_id(), 2026)
        runs = {r.payroll_run_id: r for r in s.scalars(select(PayrollRun).where(PayrollRun.frequency == "MONTHLY"))}
    if df.empty:
        st.info("No results yet.")
        return
    df = df[df["run_id"].isin(runs)]
    periods = sorted(df["period"].unique())
    period = st.select_slider("Period", options=periods, value=periods[-1])
    tabs = st.tabs(["Payroll cost", "Employees", "Departments", "Variance"])
    cur = df[df["period"] == period]
    with tabs[0]:
        c = st.columns(6)
        for i, (k, lab) in enumerate([("salary_cost", "Salary"), ("overtime", "Overtime"), ("bonus", "Bonuses"),
                                      ("prsi_er", "Employer PRSI"), ("pension_er", "Employer pension"), ("employer_cost", "Total cost")]):
            kpi(c[i], lab, eur(cur[k].sum(), 0))
        tr = an.trend(df)
        tr["other"] = tr["gross_pay"] - tr["salary_cost"] - tr["overtime"] - tr["bonus"]
        fig = go.Figure()
        for i, (col, name) in enumerate([("salary_cost", "Salary"), ("overtime", "Overtime"), ("bonus", "Bonus"), ("other", "Other earnings"),
                                         ("prsi_er", "Employer PRSI"), ("pension_er", "Employer pension")]):
            fig.add_bar(x=tr["period_label"], y=tr[col], name=name, marker_color=SERIES[i],
                        hovertemplate="%{x}<br>" + name + ": €%{y:,.0f}<extra></extra>")
        fig.update_layout(barmode="stack", yaxis_tickprefix="€")
        st.plotly_chart(style_fig(fig, 380, "Payroll cost composition by month"), use_container_width=True, theme=None)
    with tabs[1]:
        c = st.columns(2)
        with c[0]:
            fig = go.Figure()
            fig.add_histogram(x=cur["gross_pay"], name="Gross", marker_color=SERIES[0], opacity=0.85, nbinsx=30)
            fig.add_histogram(x=cur["net_pay"], name="Net", marker_color=SERIES[1], opacity=0.85, nbinsx=30)
            fig.update_layout(barmode="overlay", xaxis_tickprefix="€")
            st.plotly_chart(style_fig(fig, 340, f"Gross and net pay distribution (P{period})"), use_container_width=True, theme=None)
        with c[1]:
            d = cur.assign(deductions=cur["paye"] + cur["usc"] + cur["prsi_ee"])
            d["effective_rate"] = (d["deductions"] / d["gross_pay"] * 100).round(1)
            fig = go.Figure(go.Scatter(x=d["gross_pay"], y=d["effective_rate"], mode="markers",
                                       marker=dict(size=8, color=SERIES[0], line=dict(color="#fcfcfb", width=2)),
                                       text=d["name"], hovertemplate="%{text}<br>Gross €%{x:,.0f}<br>PAYE+USC+PRSI %{y}%<extra></extra>"))
            fig.update_layout(xaxis_tickprefix="€", yaxis_ticksuffix="%")
            st.plotly_chart(style_fig(fig, 340, "Effective deduction rate vs gross"), use_container_width=True, theme=None)
        prev = df[df["period"] == period - 1][["employee_id", "net_pay", "gross_pay"]]
        ch = cur.merge(prev, on="employee_id", suffixes=("", "_prev"))
        ch["net_change_%"] = ((ch["net_pay"] - ch["net_pay_prev"]) / ch["net_pay_prev"] * 100).round(1)
        st.markdown("**Largest net pay changes vs previous period**")
        st.dataframe(ch.reindex(ch["net_change_%"].abs().sort_values(ascending=False).index).head(15)[
            ["employee_number", "name", "department", "gross_pay_prev", "gross_pay", "net_pay_prev", "net_pay", "net_change_%"]],
            hide_index=True, use_container_width=True)
    with tabs[2]:
        dep = an.by_department(df, period)
        st.dataframe(dep, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="€%.0f") for c in
                                    ("gross_pay", "net_pay", "overtime", "bonus", "prsi_er", "pension_er", "employer_cost", "avg_salary", "budget")})
        d = dep.sort_values("avg_salary")
        fig = go.Figure(go.Bar(x=d["avg_salary"], y=d["department"], orientation="h", marker_color=SERIES[0],
                               text=[eur(v, 0) for v in d["avg_salary"]], textposition="outside"))
        fig.update_layout(xaxis_tickprefix="€")
        st.plotly_chart(style_fig(fig, 340, "Average annual salary by department"), use_container_width=True, theme=None)
    with tabs[3]:
        v = an.variance(df, period)
        st.dataframe(v, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="€%.0f") for c in ("current", "budget", "previous", "vs_previous", "vs_budget")})
        vv = v.sort_values("vs_budget_pct")
        colors = [SERIES[1] if x > 0 else SERIES[0] for x in vv["vs_budget_pct"].fillna(0)]
        fig = go.Figure(go.Bar(x=vv["vs_budget_pct"], y=vv["department"], orientation="h", marker_color=colors,
                               text=[f"{x:+.1f}%" for x in vv["vs_budget_pct"].fillna(0)], textposition="outside"))
        fig.update_layout(xaxis_ticksuffix="%", xaxis_zeroline=True, xaxis_zerolinecolor="#8a8984")
        st.plotly_chart(style_fig(fig, 340, f"Employer cost vs budget, P{period} (orange = over budget)"), use_container_width=True, theme=None)


def rules() -> None:
    guard(Perm.RULES_READ)
    page_header("Statutory rules", "Versioned, sourced and verification-gated. The engine refuses UNVERIFIED rules.")
    with db() as s:
        repo = repository_from_db(s)
    df = pd.DataFrame([r.to_dict() for r in repo.list()])
    c = st.columns(4)
    kpi(c[0], "Rules", str(len(df)))
    kpi(c[1], "Verified", str((df["status"] == "VERIFIED").sum()))
    kpi(c[2], "Unverified (blocked)", str((df["status"] != "VERIFIED").sum()))
    kpi(c[3], "Tax years", ", ".join(str(x) for x in sorted(df["tax_year"].unique())))
    c = st.columns(3)
    yr = c[0].multiselect("Tax year", sorted(df["tax_year"].unique()), default=[2026])
    cat = c[1].multiselect("Category", sorted(df["category"].unique()))
    stt = c[2].multiselect("Status", sorted(df["status"].unique()))
    v = df[df["tax_year"].isin(yr)] if yr else df
    if cat:
        v = v[v["category"].isin(cat)]
    if stt:
        v = v[v["status"].isin(stt)]
    v = v.assign(value=v["value"].map(lambda x: x if isinstance(x, str) else json.dumps(x)),
                 status=v["status"].map(lambda x: "✅ VERIFIED" if x == "VERIFIED" else f"🚫 {x}"))
    st.dataframe(v[["rule_id", "category", "parameter", "value", "effective_from", "effective_to", "status", "source", "source_url",
                    "source_document", "verified_date", "notes"]], hide_index=True, use_container_width=True, height=460,
                 column_config={"source_url": st.column_config.LinkColumn("Source URL")})
    if can(Perm.RULES_WRITE):
        with st.form("rule_status"):
            st.markdown("**Change verification status** (system administrator; audited)")
            c = st.columns([2, 1, 3])
            rid = c[0].selectbox("Rule", df["rule_id"].tolist())
            new = c[1].selectbox("Status", ["VERIFIED", "UNVERIFIED", "SUPERSEDED"])
            reason = c[2].text_input("Evidence / reason (required)")
            if st.form_submit_button("Update"):
                try:
                    with db() as s:
                        set_rule_status(s, rid, new, current_user_obj(s), reason)
                    st.success("Rule updated.")
                except ValueError as exc:
                    st.error(str(exc))


def revenue() -> None:
    guard(Perm.REVENUE_PREPARE)
    page_header("Revenue submission preparation",
                "Builds and validates payroll submission data. Nothing is transmitted to Revenue from this prototype.")
    st.info("Direct submission requires Revenue's PAYE Modernisation API, a ROS digital certificate and message signing, which "
            "are not implemented. Export the prepared file instead — see REVENUE_INTEGRATION.md.", icon="ℹ️")
    with db() as s:
        run = _pick_run(s, "rev_run", statuses=FINAL_STATUSES)
        if not run:
            return
        if run.status == "APPROVED" and st.button("Prepare submission data", type="primary"):
            sub = prepare_submission(s, current_user_obj(s), run)
            if sub.status == "PREPARED":
                mark_submitted(s, current_user_obj(s), run)
            st.rerun()
        subs = s.scalars(select(RevenueSubmission).where(RevenueSubmission.payroll_run_id == run.payroll_run_id)
                         .order_by(RevenueSubmission.prepared_at.desc())).all()
        if not subs:
            st.caption("No submission prepared for this run yet." + ("" if run.status == "APPROVED" else
                                                                      " (Historical demo runs were completed without one.)"))
            if run.status != "APPROVED" and st.button("Prepare submission data (re-export)"):
                prepare_submission(s, current_user_obj(s), run)
                st.rerun()
            return
        sub = subs[0]
        c = st.columns(4)
        kpi(c[0], "Reference", sub.submission_ref)
        kpi(c[1], "Status", sub.status)
        kpi(c[2], "Payslip lines", str(len(sub.payload["payslips"])))
        kpi(c[3], "Validation issues", str(len(sub.validation_errors or [])))
        if sub.validation_errors:
            st.dataframe(pd.DataFrame(sub.validation_errors), hide_index=True, use_container_width=True)
        lines = pd.json_normalize(sub.payload["payslips"])
        lines["employeeID.employeePpsn"] = lines["employeeID.employeePpsn"].map(lambda p: "•••••" + p[-3:] if p else None)
        st.dataframe(lines, hide_index=True, use_container_width=True, height=340)
        st.download_button("⬇️ Export submission JSON", export_json(sub), f"{sub.submission_ref}.json", "application/json")
        st.caption(sub.payload["schemaNote"])


def audit_log() -> None:
    guard(Perm.AUDIT_READ)
    page_header("Audit log", "Every material action with user, time, before/after values and reason")
    with db() as s:
        rows = s.scalars(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(3000)).all()
        df = pd.DataFrame([{"When": a.timestamp, "User": a.user_email, "Action": a.action, "Entity": a.entity, "Entity ID": a.entity_id,
                            "Before": json.dumps(a.before_value) if a.before_value else "",
                            "After": json.dumps(a.after_value) if a.after_value else "", "Reason": a.reason} for a in rows])
    c = st.columns(3)
    act = c[0].multiselect("Action", sorted(df["Action"].unique()))
    usr = c[1].multiselect("User", sorted(df["User"].dropna().unique()))
    q = c[2].text_input("Search entity id / reason")
    if act:
        df = df[df["Action"].isin(act)]
    if usr:
        df = df[df["User"].isin(usr)]
    if q:
        df = df[df["Entity ID"].fillna("").str.contains(q) | df["Reason"].fillna("").str.contains(q, case=False)]
    st.dataframe(df, hide_index=True, use_container_width=True, height=520)
    st.download_button("⬇️ Export audit CSV", df.to_csv(index=False), "audit_log.csv", "text/csv")


def settings() -> None:
    page_header("Settings")
    with db() as s:
        co = s.get(Company, company_id())
        st.markdown("#### Company")
        st.markdown(f"**{co.legal_name}** ({co.trading_name}) · Employer reg. `{co.tax_registration_number}` · {co.address}  \n"
                    f"Default frequency {co.payroll_frequency.title()} · Financial year {co.financial_year}")
        st.markdown("#### Your access")
        u = user()
        st.markdown(f"Signed in as **{u['email']}** — role `{u['role']}`")
        st.markdown(", ".join(f"`{p.value}`" for p in sorted(ROLE_PERMISSIONS[Role(u["role"])], key=lambda p: p.value)))
        if can(Perm.USERS_MANAGE):
            st.markdown("#### Users")
            st.dataframe(pd.DataFrame([{"Email": x.email, "Name": x.full_name, "Role": x.role, "Active": x.is_active,
                                        "Last login": x.last_login_at} for x in s.scalars(select(User))]),
                         hide_index=True, use_container_width=True)
            st.markdown("#### Role permission matrix")
            perms = sorted(p.value for p in Perm)
            st.dataframe(pd.DataFrame({r.value: ["✅" if Perm(p) in ROLE_PERMISSIONS[r] else "" for p in perms] for r in Role}, index=perms),
                         use_container_width=True)
