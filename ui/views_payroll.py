"""Dashboard, calendar, runs, calculation drill-down, exceptions, payslips."""

from __future__ import annotations

import calendar as cal
from datetime import date
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.security import Perm
from app.db.models import Employee, PayrollException, PayrollResultRecord, PayrollRun
from app.services import analytics as an
from app.services import payroll_service as ps
from app.services.payslips import generate_payslips, render_html, render_pdf
from app.services.reconciliation import reconcile_run
from app.services.revenue import prepare_submission
from ui.common import (
    RUN_BADGE,
    SERIES,
    SEVERITY_ICON,
    STATUS,
    can,
    company_id,
    current_user_obj,
    db,
    eur,
    guard,
    kpi,
    page_header,
    style_fig,
)


def _runs(s, freq: str | None = None) -> list[PayrollRun]:
    q = select(PayrollRun).where(PayrollRun.company_id == company_id())
    if freq:
        q = q.where(PayrollRun.frequency == freq)
    return list(s.scalars(q.order_by(PayrollRun.payment_date.desc(), PayrollRun.frequency, PayrollRun.payroll_run_id.desc())))


def _run_label(r: PayrollRun) -> str:
    kind = "" if r.run_type == "REGULAR" else f" · {r.run_type.lower()}"
    return f"#{r.payroll_run_id} · {r.frequency.title()} P{r.payroll_period} · paid {r.payment_date:%d %b %Y} · {RUN_BADGE[r.status]}{kind}"


def _pick_run(s, key: str, statuses: tuple[str, ...] | None = None, freq: str | None = None) -> PayrollRun | None:
    runs = [r for r in _runs(s, freq) if not statuses or r.status in statuses]
    if not runs:
        st.info("No payroll runs yet.")
        return None
    ids = [r.payroll_run_id for r in runs]
    default = st.session_state.get("run_id")
    idx = ids.index(default) if default in ids else 0
    rid = st.selectbox("Payroll run", ids, index=idx, format_func=lambda i: _run_label(next(r for r in runs if r.payroll_run_id == i)), key=key)
    st.session_state.run_id = rid
    return next(r for r in runs if r.payroll_run_id == rid)


# ====================================================================== dashboard


def dashboard() -> None:
    page_header("Payroll dashboard", "Executive view of the current payroll and the year to date")
    freq = st.segmented_control("Pay frequency", ["MONTHLY", "WEEKLY"], default="MONTHLY", format_func=str.title)
    with db() as s:
        runs = [r for r in _runs(s, freq) if r.status != "REVERSED" and r.totals]
        if not runs:
            st.info("No calculated payroll yet.")
            return
        cur = runs[0]
        prev = next((r for r in runs[1:] if r.payroll_period < cur.payroll_period), None)
        t, pt = cur.totals, (prev.totals if prev else {})
        n_exc = len(s.scalars(select(PayrollException.exception_id).where(
            PayrollException.payroll_run_id == cur.payroll_run_id, PayrollException.status == "OPEN")).all())
        df = an.results_frame(s, company_id(), cur.tax_year)

    st.markdown(f"**Current run:** {_run_label(cur)}")

    def delta(k):
        if not pt or k not in pt or Decimal(pt[k]) == 0:
            return None
        return f"{(Decimal(t[k]) - Decimal(pt[k])) / Decimal(pt[k]) * 100:+.1f}% vs P{prev.payroll_period}"

    c = st.columns(6)
    kpi(c[0], "Total employer cost", eur(t["employer_cost"], 0), delta("employer_cost"))
    kpi(c[1], "Gross pay", eur(t["gross_pay"], 0), delta("gross_pay"))
    kpi(c[2], "Net pay", eur(t["net_pay"], 0), delta("net_pay"))
    kpi(c[3], "Statutory liability", eur(t["statutory_liability"], 0), delta("statutory_liability"),
        "PAYE + USC + employee PRSI + employer PRSI + LPT")
    kpi(c[4], "Employees processed", f"{t['employees_processed']}", f"{t['employees_with_errors']} with errors",
        )
    kpi(c[5], "Open exceptions", str(n_exc), None)
    c = st.columns(6)
    kpi(c[0], "PAYE", eur(t["paye"], 0), delta("paye"))
    kpi(c[1], "USC", eur(t["usc"], 0), delta("usc"))
    kpi(c[2], "Employee PRSI", eur(t["prsi_ee"], 0), delta("prsi_ee"))
    kpi(c[3], "Employer PRSI", eur(t["prsi_er"], 0), delta("prsi_er"))
    kpi(c[4], "LPT", eur(t["lpt"], 0), delta("lpt"))
    kpi(c[5], "Payroll variance", delta("employer_cost") or "—", help="Employer cost vs previous period")

    df = df[df["run_id"].isin([r.payroll_run_id for r in runs])] if not df.empty else df
    if df.empty:
        return
    tr = an.trend(df)
    lab = tr["period_label"] if freq == "MONTHLY" else "W" + tr["period"].astype(str)
    left, right = st.columns(2)
    with left:
        fig = go.Figure()
        for i, (col, name) in enumerate([("gross_pay", "Gross pay"), ("prsi_er", "Employer PRSI"), ("pension_er", "Employer pension"),
                                         ("bik", "Benefits (BIK)")]):
            fig.add_bar(x=lab, y=tr[col], name=name, marker_color=SERIES[i],
                        hovertemplate="%{x}<br>" + name + ": €%{y:,.0f}<extra></extra>")
        fig.update_layout(barmode="stack", yaxis_tickprefix="€")
        st.plotly_chart(style_fig(fig, title="Payroll cost trend (employer cost build-up)"), use_container_width=True, theme=None)
    with right:
        fig = go.Figure()
        fig.add_scatter(x=lab, y=tr["gross_pay"], name="Gross", mode="lines+markers", line=dict(width=2, color=SERIES[0]),
                        marker=dict(size=8))
        fig.add_scatter(x=lab, y=tr["net_pay"], name="Net", mode="lines+markers", line=dict(width=2, color=SERIES[1]),
                        marker=dict(size=8))
        fig.update_layout(yaxis_tickprefix="€", hovermode="x unified")
        st.plotly_chart(style_fig(fig, title="Gross vs net pay"), use_container_width=True, theme=None)

    left, right = st.columns(2)
    with left:
        fig = go.Figure()
        for i, (col, name) in enumerate([("paye", "PAYE"), ("usc", "USC"), ("prsi_ee", "Employee PRSI"), ("prsi_er", "Employer PRSI"), ("lpt", "LPT")]):
            fig.add_bar(x=lab, y=tr[col], name=name, marker_color=SERIES[i],
                        hovertemplate="%{x}<br>" + name + ": €%{y:,.0f}<extra></extra>")
        fig.update_layout(barmode="stack", yaxis_tickprefix="€")
        st.plotly_chart(style_fig(fig, title="Statutory deductions & employer PRSI"), use_container_width=True, theme=None)
    with right:
        d = an.by_department(df, cur.payroll_period).sort_values("employer_cost")
        fig = go.Figure(go.Bar(x=d["employer_cost"], y=d["department"], orientation="h", marker_color=SERIES[0],
                               text=[eur(v, 0) for v in d["employer_cost"]], textposition="outside",
                               hovertemplate="%{y}: €%{x:,.0f}<extra></extra>"))
        fig.update_layout(xaxis_tickprefix="€", xaxis_showgrid=True, yaxis_gridcolor="rgba(0,0,0,0)")
        st.plotly_chart(style_fig(fig, title=f"Employer cost by department (P{cur.payroll_period})"), use_container_width=True, theme=None)

    left, mid, right = st.columns(3)
    with left:
        top = an.top_overtime(df, cur.payroll_period, 8).sort_values("overtime")
        fig = go.Figure(go.Bar(x=top["overtime"], y=top["name"], orientation="h", marker_color=SERIES[1],
                               hovertemplate="%{y}: €%{x:,.2f}<extra></extra>"))
        st.plotly_chart(style_fig(fig, 300, "Top overtime (current period)"), use_container_width=True, theme=None)
    with mid:
        b = df[df["bonus"] > 0]
        fig = go.Figure(go.Histogram(x=b["bonus"], nbinsx=12, marker_color=SERIES[2], marker_line_color="#fcfcfb",
                                     marker_line_width=2, hovertemplate="€%{x}: %{y} payments<extra></extra>"))
        fig.update_layout(xaxis_tickprefix="€")
        st.plotly_chart(style_fig(fig, 300, "Bonus distribution (YTD)"), use_container_width=True, theme=None)
    with right:
        with db() as s:
            ex = an.exceptions_frame(s, cur.payroll_run_id)
        if not ex.empty:
            ex = ex[ex["status"] == "OPEN"]
            order = ["CRITICAL", "ERROR", "WARNING", "INFO"]
            cnt = ex.groupby("severity").size().reindex(order, fill_value=0)
            colors = [STATUS["critical"], STATUS["serious"], STATUS["warning"], "#86b6ef"]
            fig = go.Figure(go.Bar(x=[SEVERITY_ICON[x] for x in order], y=cnt.values, marker_color=colors,
                                   text=cnt.values, textposition="outside"))
            st.plotly_chart(style_fig(fig, 300, "Open exceptions (current run)"), use_container_width=True, theme=None)


# ====================================================================== calendar


def calendar() -> None:
    page_header("Payroll calendar", "Pay dates, run status and statutory milestones")
    year = 2026
    with db() as s:
        runs = _runs(s)
    by_date: dict[date, list[PayrollRun]] = {}
    for r in runs:
        by_date.setdefault(r.payment_date, []).append(r)
    month = st.select_slider("Month", options=list(range(1, 13)), value=min(date.today().month, 12),
                             format_func=lambda m: cal.month_name[m])
    st.markdown(f"#### {cal.month_name[month]} {year}")
    weeks = cal.Calendar(firstweekday=0).monthdatescalendar(year, month)
    hdr = st.columns(7)
    for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        hdr[i].markdown(f"**{d}**")
    for wk in weeks:
        cols = st.columns(7)
        for i, d in enumerate(wk):
            with cols[i].container(border=True, height=110):
                faded = d.month != month
                st.markdown(f"<span style='color:{'#b0afa8' if faded else '#0b0b0b'}'>{d.day}</span>", unsafe_allow_html=True)
                for r in by_date.get(d, []):
                    st.caption(f"{RUN_BADGE[r.status].split()[0]} {r.frequency[0]}P{r.payroll_period} pay day")
                if d == date(year, 10, 1):
                    st.caption("⚖️ PRSI +0.15% (1 Oct)")
    st.caption("Rule-change dates come from the versioned rule store. Revenue return/payment due dates are not shown because "
               "they were not verified in this build.")


# ====================================================================== runs


def runs() -> None:
    guard(Perm.PAYROLL_READ)
    page_header("Payroll runs", "Create → calculate → validate → review exceptions → approve → submission prep → complete")
    with db() as s:
        rows = _runs(s)
        table = pd.DataFrame([{"Run": r.payroll_run_id, "Frequency": r.frequency.title(), "Period": r.payroll_period,
                               "Pay date": r.payment_date, "Type": r.run_type.title(), "Status": RUN_BADGE[r.status],
                               "Employees": (r.totals or {}).get("employees_processed"),
                               "Gross": float((r.totals or {}).get("gross_pay", 0)),
                               "Net": float((r.totals or {}).get("net_pay", 0)),
                               "Employer cost": float((r.totals or {}).get("employer_cost", 0)),
                               "Calc (s)": r.calc_seconds} for r in rows])
    f = st.segmented_control("Show", ["All", "MONTHLY", "WEEKLY"], default="All")
    if f and f != "All":
        table = table[table["Frequency"] == f.title()]
    st.dataframe(table, hide_index=True, use_container_width=True, height=260,
                 column_config={c: st.column_config.NumberColumn(format="€%.2f") for c in ("Gross", "Net", "Employer cost")})

    if can(Perm.PAYROLL_RUN):
        with st.expander("➕ Create a payroll run"):
            _create_run_form()

    st.divider()
    with db() as s:
        run = _pick_run(s, "runs_pick")
        if not run:
            return
        _run_detail(s, run)


def _create_run_form() -> None:
    with st.form("new_run"):
        c = st.columns(4)
        freq = c[0].selectbox("Frequency", ["MONTHLY", "WEEKLY"])
        period = c[1].number_input("Period", 1, 53, 10)
        year = c[2].number_input("Tax year", 2025, 2030, 2026)
        pay = c[3].date_input("Payment date", date(2026, 10, 23))
        c = st.columns(2)
        start = c[0].date_input("Period start", date(2026, 10, 1))
        end = c[1].date_input("Period end", date(2026, 10, 31))
        if st.form_submit_button("Create run", type="primary"):
            try:
                with db() as s:
                    r = ps.create_run(s, current_user_obj(s), company_id(), int(year), freq, int(period), start, end, pay)
                    st.session_state.run_id = r.payroll_run_id
                st.success(f"Run #{st.session_state.run_id} created as DRAFT.")
                st.rerun()
            except ps.WorkflowError as exc:
                st.error(str(exc))


def _run_detail(s, run: PayrollRun) -> None:
    u = current_user_obj(s)
    t = run.totals or {}
    st.markdown(f"### Run #{run.payroll_run_id} — {RUN_BADGE[run.status]}")
    st.caption(f"{run.frequency.title()} period {run.payroll_period}/{run.tax_year} · {run.period_start:%d %b} – "
               f"{run.period_end:%d %b %Y} · paid {run.payment_date:%d %b %Y}"
               + (f" · calculated in {run.calc_seconds}s" if run.calc_seconds else ""))
    if t:
        c = st.columns(4)
        kpi(c[0], "Employees processed", str(t["employees_processed"]))
        kpi(c[1], "Successful", str(t["employees_successful"]))
        kpi(c[2], "With errors", str(t["employees_with_errors"]))
        kpi(c[3], "Requiring review", str(t["employees_requiring_review"]))
        c = st.columns(5)
        for i, (k, lab) in enumerate([("gross_pay", "Gross"), ("paye", "PAYE"), ("usc", "USC"), ("prsi_ee", "Employee PRSI"),
                                      ("prsi_er", "Employer PRSI")]):
            kpi(c[i], lab, eur(t[k]))
        c = st.columns(4)
        for i, (k, lab) in enumerate([("lpt", "LPT"), ("net_pay", "Net pay"), ("employer_cost", "Employer cost"),
                                      ("statutory_liability", "Statutory liability")]):
            kpi(c[i], lab, eur(t[k]))

    blocking = ps.blocking_exceptions(s, run)
    b = st.columns(6)
    if can(Perm.PAYROLL_RUN) and run.status in ps.EDITABLE:
        if b[0].button("⚙️ Calculate" if not run.calculated_at else "🔁 Recalculate", type="primary", use_container_width=True):
            with st.spinner("Calculating payroll…"):
                ps.calculate_run(s, u, run)
            st.rerun()
    if can(Perm.PAYROLL_APPROVE) and run.status == "READY_FOR_APPROVAL":
        if b[1].button("✅ Approve", type="primary", use_container_width=True):
            try:
                ps.approve_run(s, u, run)
                generate_payslips(s, u, run)
                st.rerun()
            except ps.WorkflowError as exc:
                st.error(str(exc))
    if run.status == "VALIDATION_REQUIRED":
        b[1].button(f"⛔ {blocking} blocking exception(s)", disabled=True, use_container_width=True)
    if can(Perm.REVENUE_PREPARE) and run.status == "APPROVED":
        if b[2].button("🏛️ Prepare submission", use_container_width=True):
            sub = prepare_submission(s, u, run)
            if sub.status == "PREPARED":
                ps.mark_submitted(s, u, run)
                st.success(f"Submission {sub.submission_ref} prepared.")
            else:
                st.error(f"Submission failed validation: {sub.validation_errors[:3]}")
            st.rerun()
    if can(Perm.PAYROLL_APPROVE) and run.status == "SUBMITTED":
        if b[3].button("🏁 Complete", use_container_width=True):
            ps.complete_run(s, u, run)
            st.rerun()
    if can(Perm.PAYROLL_APPROVE) and run.status in ps.FINAL_STATUSES:
        with b[4].popover("↩️ Reverse", use_container_width=True):
            reason = st.text_input("Reason (required)", key="rev_reason")
            if st.button("Confirm reversal", type="primary", disabled=len(reason) < 5):
                corr = ps.reverse_run(s, u, run, reason)
                st.session_state.run_id = corr.payroll_run_id
                st.rerun()

    tabs = st.tabs(["Results", "Inputs", "Reconciliation"])
    with tabs[0]:
        from app.services.reports import register
        reg = register(s, run)
        if reg.empty:
            st.info("Not calculated yet.")
        else:
            q = st.text_input("Search employee", key="reg_search")
            if q:
                reg = reg[reg["name"].str.contains(q, case=False) | reg["employee_number"].str.contains(q, case=False)]
            st.dataframe(reg[["employee_number", "name", "department", "status", "tax_basis", "prsi_subclass", "gross_pay",
                              "paye", "usc", "prsi_ee", "lpt", "pension_ee", "net_pay", "prsi_er", "employer_cost", "error"]],
                         hide_index=True, use_container_width=True, height=380,
                         column_config={c: st.column_config.NumberColumn(format="€%.2f") for c in
                                        ("gross_pay", "paye", "usc", "prsi_ee", "lpt", "pension_ee", "net_pay", "prsi_er", "employer_cost")})
            st.caption("Open **Payroll Calculation** to see why any figure is what it is.")
    with tabs[1]:
        _inputs_tab(s, run)
    with tabs[2]:
        if run.totals:
            rec = pd.DataFrame(reconcile_run(s, run, record=False))
            rec["status"] = rec["status"].map({"OK": "✅ OK", "MISMATCH": "🛑 MISMATCH"})
            st.dataframe(rec, hide_index=True, use_container_width=True)


def _inputs_tab(s, run: PayrollRun) -> None:
    editable = can(Perm.PAYROLL_RUN) and run.status in ps.EDITABLE
    st.caption("Basic salary / standard hourly pay is generated from the employee record (pro-rated for joiners and leavers). "
               "Enter variable pay here. Changing inputs returns the run to DRAFT.")
    from app.db.models import PayrollInputRecord
    recs = s.scalars(select(PayrollInputRecord).where(PayrollInputRecord.payroll_run_id == run.payroll_run_id)
                     .options(selectinload(PayrollInputRecord.earnings), selectinload(PayrollInputRecord.deductions))).all()
    emps = {e.employee_id: e for e in s.scalars(select(Employee).where(Employee.company_id == run.company_id))}
    rows = [{"Employee": emps[r.employee_id].employee_number, "Name": emps[r.employee_id].full_name, "Type": e.earning_type,
             "Description": e.description, "Amount": float(e.amount)} for r in recs for e in r.earnings]
    rows += [{"Employee": emps[r.employee_id].employee_number, "Name": emps[r.employee_id].full_name, "Type": f"DEDUCTION:{d.code}",
              "Description": d.description, "Amount": float(d.amount)} for r in recs for d in r.deductions]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=240)
    if not editable:
        return
    c1, c2 = st.columns(2)
    with c1.form("add_input"):
        st.markdown("**Add a variable earning / deduction**")
        eid = st.selectbox("Employee", sorted(emps), format_func=lambda i: f"{emps[i].employee_number} · {emps[i].full_name}")
        kind = st.selectbox("Type", ["OVERTIME", "BONUS", "COMMISSION", "HOLIDAY_PAY", "ALLOWANCE", "SHIFT_PREMIUM", "ARREARS",
                                     "BACK_PAY", "OTHER_TAXABLE", "ADJUSTMENT", "DEDUCTION:UNION", "DEDUCTION:SALARY_ADVANCE"])
        amt = st.number_input("Amount (€)", value=0.0, step=10.0)
        desc = st.text_input("Description")
        if st.form_submit_button("Add"):
            if kind.startswith("DEDUCTION:"):
                ps.set_inputs(s, current_user_obj(s), run, eid, [], [{"code": kind.split(":")[1], "amount": Decimal(str(amt)),
                                                                       "description": desc}], replace=False)
            else:
                ps.set_inputs(s, current_user_obj(s), run, eid, [{"type": kind, "amount": Decimal(str(amt)), "description": desc}],
                              replace=False)
            st.rerun()
    with c2:
        st.markdown("**Bulk import (CSV)**")
        st.caption("Columns: employee_number,type,amount,description,hours — type is an earning type or DEDUCTION:<code>")
        up = st.file_uploader("Payroll inputs CSV", type="csv", key="inputs_csv")
        if up and st.button("Import inputs"):
            res = ps.import_inputs_csv(s, current_user_obj(s), run, up.getvalue().decode("utf-8-sig"))
            st.success(f"Imported inputs for {res['employees']} employees; {len(res['errors'])} errors.")
            if res["errors"]:
                st.dataframe(pd.DataFrame(res["errors"]))


# ====================================================================== calculation drill-down


COMPONENTS = [("GROSS", "Gross & pay bases"), ("BIK", "Benefit in kind"), ("PENSION", "Pension"), ("PAYE", "PAYE"),
              ("USC", "USC"), ("PRSI", "PRSI"), ("LPT", "LPT"), ("NET", "Net pay"), ("EMPLOYER", "Employer cost"),
              ("LIABILITY", "Statutory liability")]


def calculation() -> None:
    guard(Perm.PAYROLL_READ)
    page_header("Payroll calculation", "Every figure with its calculation steps, rule version and official source")
    with db() as s:
        run = _pick_run(s, "calc_run")
        if not run:
            return
        res = s.scalars(select(PayrollResultRecord).where(PayrollResultRecord.payroll_run_id == run.payroll_run_id)
                        .options(selectinload(PayrollResultRecord.employee))).all()
        if not res:
            st.info("This run has not been calculated.")
            return
        opts = {r.result_id: f"{r.employee.employee_number} · {r.employee.full_name}" + ("" if r.status == "CALCULATED" else f" · ⛔ {r.status}")
                for r in sorted(res, key=lambda x: x.employee.employee_number)}
        default = st.session_state.get("result_id")
        keys = list(opts)
        rid = st.selectbox("Employee", keys, index=keys.index(default) if default in keys else 0, format_func=opts.get)
        st.session_state.result_id = rid
        r = s.get(PayrollResultRecord, rid)
        trace, msgs, rules_used = r.trace or [], r.messages or [], r.rules_used or []

        if r.status != "CALCULATED":
            st.error(f"**Unable to calculate reliably** — {r.error_message}  \nStatus: `{r.status}` · code `{r.error_code}`")
        else:
            c = st.columns(4)
            kpi(c[0], "Gross pay", eur(r.gross_pay))
            kpi(c[1], "Net pay", eur(r.net_pay))
            kpi(c[2], "Employer cost", eur(r.employer_cost))
            kpi(c[3], "Statutory liability", eur(r.statutory_liability))
            left, right = st.columns([1.1, 1])
            with left:
                fig = go.Figure(go.Waterfall(
                    orientation="v", measure=["absolute", "relative", "relative", "relative", "relative", "relative", "relative", "total"],
                    x=["Gross", "PAYE", "USC", "PRSI", "LPT", "Pension", "Other", "Net"],
                    y=[float(r.gross_pay), -float(r.paye), -float(r.usc), -float(r.prsi_ee), -float(r.lpt), -float(r.pension_ee),
                       -float(r.other_deductions), 0],
                    increasing=dict(marker_color=SERIES[0]), decreasing=dict(marker_color=SERIES[1]), totals=dict(marker_color=SERIES[2]),
                    connector=dict(line=dict(color="#d4d4d0", width=1)),
                    text=[eur(r.gross_pay)] + [f"−{eur(v)}" for v in (r.paye, r.usc, r.prsi_ee, r.lpt, r.pension_ee, r.other_deductions)]
                    + [eur(r.net_pay)], textposition="outside"))
                fig.update_layout(yaxis_tickprefix="€", showlegend=False)
                st.plotly_chart(style_fig(fig, 330, "Gross to net"), use_container_width=True, theme=None)
            with right:
                st.markdown("**Employee deductions**")
                st.table(pd.DataFrame([["PAYE", eur(r.paye)], ["USC", eur(r.usc)], [f"Employee PRSI ({r.prsi_subclass})", eur(r.prsi_ee)],
                                       ["LPT", eur(r.lpt)], ["Employee pension", eur(r.pension_ee)], ["Other", eur(r.other_deductions)]],
                                      columns=["Deduction", "Amount"]).set_index("Deduction"))
                st.markdown(f"Tax basis **{r.tax_basis_applied}** · USC **{r.usc_status_applied}** · Employer PRSI **{eur(r.prsi_er)}**")
        for m in msgs:
            st.warning(f"{SEVERITY_ICON.get(m['severity'], m['severity'])} `{m['code']}` — {m['message']}")

        st.markdown("### Why is each figure what it is?")
        for comp, label in COMPONENTS:
            steps = [t for t in trace if t["component"] == comp]
            if not steps:
                continue
            final = steps[-1]["result"]
            with st.expander(f"**{label}** — result {eur(final) if _num(final) else final}", expanded=comp in ("PAYE",)):
                for t in steps:
                    cols = st.columns([1.2, 3, 0.9])
                    cols[0].markdown(f"**{t['step']}**  \n<span class='small'>{t['description']}</span>", unsafe_allow_html=True)
                    cols[1].code(t["calculation"], language=None)
                    cols[2].markdown(f"**{eur(t['result']) if _num(t['result']) else t['result']}**"
                                     + (f"  \n<span class='small'>rate {t['rate']}</span>" if t.get("rate") else ""), unsafe_allow_html=True)
                    if t.get("rule"):
                        ru = t["rule"]
                        st.caption(f"Rule `{ru['rule_id']}` · {ru['rule_version']} · effective {ru['effective_from']}–{ru['effective_to'] or 'open'} · "
                                   f"[{ru['source']}]({ru['source_url']}) · verified {ru['verified_date']} · {ru['status']}")
        st.caption("Rules used: " + ", ".join(f"`{x}`" for x in rules_used))


def _num(v) -> bool:
    try:
        Decimal(str(v))
        return True
    except Exception:  # noqa: BLE001
        return False


# ====================================================================== exceptions


def exceptions() -> None:
    guard(Perm.PAYROLL_READ)
    page_header("Exception queue", "Engine blocks, validation failures, anomalies and reconciliation breaks")
    with db() as s:
        run = _pick_run(s, "exc_run")
        if not run:
            return
        df = an.exceptions_frame(s, run.payroll_run_id)
    if df.empty:
        st.success("No exceptions for this run.")
        return
    c = st.columns(4)
    sev = c[0].multiselect("Severity", ["CRITICAL", "ERROR", "WARNING", "INFO"], default=["CRITICAL", "ERROR", "WARNING"])
    stat = c[1].multiselect("Status", ["OPEN", "ACKNOWLEDGED", "RESOLVED"], default=["OPEN"])
    src = c[2].multiselect("Source", sorted(df["source"].unique()), default=sorted(df["source"].unique()))
    q = c[3].text_input("Search")
    v = df[df["severity"].isin(sev) & df["status"].isin(stat) & df["source"].isin(src)]
    if q:
        v = v[v["message"].str.contains(q, case=False) | v["employee"].str.contains(q, case=False) | v["code"].str.contains(q, case=False)]
    counts = df[df["status"] == "OPEN"].groupby("severity").size()
    m = st.columns(4)
    for i, sv in enumerate(["CRITICAL", "ERROR", "WARNING", "INFO"]):
        kpi(m[i], SEVERITY_ICON[sv], str(int(counts.get(sv, 0))), "open")
    v = v.assign(severity=v["severity"].map(SEVERITY_ICON))
    st.dataframe(v[["exception_id", "severity", "source", "code", "employee_number", "employee", "message", "status", "resolution_note"]],
                 hide_index=True, use_container_width=True, height=380)
    if not can(Perm.PAYROLL_RUN):
        return
    with st.form("resolve"):
        st.markdown("**Resolve or acknowledge**  \n<span class='small'>CRITICAL items must be fixed at source and the run recalculated; "
                    "they cannot be acknowledged.</span>", unsafe_allow_html=True)
        c = st.columns([1, 1, 3])
        xid = c[0].selectbox("Exception", v["exception_id"].tolist())
        new = c[1].selectbox("Mark as", ["ACKNOWLEDGED", "RESOLVED"])
        note = c[2].text_input("Resolution note (required)")
        if st.form_submit_button("Save", type="primary"):
            try:
                with db() as s:
                    ps.resolve_exception(s, current_user_obj(s), s.get(PayrollException, int(xid)), note, new)
                st.rerun()
            except ps.WorkflowError as exc:
                st.error(str(exc))


# ====================================================================== payslips


def payslips() -> None:
    guard(Perm.PAYROLL_READ)
    page_header("Payslips", "Generated for approved payroll; HTML and PDF")
    with db() as s:
        run = _pick_run(s, "slip_run", statuses=ps.FINAL_STATUSES)
        if not run:
            return
        res = s.scalars(select(PayrollResultRecord).where(PayrollResultRecord.payroll_run_id == run.payroll_run_id,
                                                          PayrollResultRecord.status == "CALCULATED")
                        .options(selectinload(PayrollResultRecord.employee), selectinload(PayrollResultRecord.result_deductions))).all()
        opts = {r.result_id: f"{r.employee.employee_number} · {r.employee.full_name}" for r in sorted(res, key=lambda x: x.employee.employee_number)}
        rid = st.selectbox("Employee", list(opts), format_func=opts.get)
        r = next(x for x in res if x.result_id == rid)
        html = render_html(s, r)
        c = st.columns(3)
        c[0].download_button("⬇️ HTML payslip", html, f"payslip_{r.employee.employee_number}_P{run.payroll_period}.html", "text/html")
        c[1].download_button("⬇️ PDF payslip", render_pdf(s, r), f"payslip_{r.employee.employee_number}_P{run.payroll_period}.pdf",
                             "application/pdf")
        if can(Perm.PAYROLL_APPROVE) and c[2].button("Regenerate all payslips for run"):
            n = generate_payslips(s, current_user_obj(s), run)
            st.success(f"{n} payslips generated.")
    components.html(html, height=900, scrolling=True)

