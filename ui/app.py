"""Streamlit front end.  Run:  streamlit run ui/app.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Streamlit Cloud: copy root-level secrets into environment variables so the app settings see them
import os  # noqa: E402

import streamlit as st  # noqa: E402

try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float, bool)):
            os.environ.setdefault(_k, str(_v))
except Exception:  # noqa: BLE001 - no secrets file locally is fine
    pass
from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import Perm, verify_password  # noqa: E402
from app.db.base import utcnow  # noqa: E402
from app.db.models import User  # noqa: E402
from app.services.audit import audit  # noqa: E402
from ui import views_admin, views_payroll, views_people  # noqa: E402
from ui.common import can, db, read_only, user  # noqa: E402

st.set_page_config(page_title="Irish Payroll", page_icon="💶", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
[data-testid="stMetricValue"]{font-size:1.45rem}
.block-container{padding-top:1.4rem;max-width:1400px}
div[data-testid="stSidebarNav"] span{font-size:0.92rem}
.small{color:#52514e;font-size:0.82rem}
</style>""", unsafe_allow_html=True)


def _enter_demo() -> None:
    """Public demo: sign the visitor in as the read-only viewer (no password shown or needed)."""
    from app.core.security import DEMO_VIEWER_EMAIL

    with db() as s:
        u = s.scalar(select(User).where(User.email == DEMO_VIEWER_EMAIL, User.is_active.is_(True)))
        if u:
            st.session_state.user = {"user_id": u.user_id, "email": u.email, "name": u.full_name, "role": u.role}
            st.session_state.pop("owner_login", None)


def login() -> None:
    cfg = get_settings()
    c = st.columns([1, 1.2, 1])[1]
    with c:
        st.markdown("### 💶 Irish Payroll Management & Compliance")
        st.caption("Portfolio prototype · synthetic data · 2026 Revenue/DSP rules with sources")
        with st.form("login"):
            email = st.text_input("Email")
            pw = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if ok:
            with db() as s:
                u = s.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
                if u and verify_password(pw, u.password_hash):
                    u.last_login_at = utcnow()
                    audit(s, u, "LOGIN", "user", u.user_id)
                    st.session_state.user = {"user_id": u.user_id, "email": u.email, "name": u.full_name, "role": u.role}
                    st.session_state.pop("owner_login", None)
                    st.rerun()
                audit(s, None, "LOGIN_FAILED", "user", None, None, {"email": email})
            st.error("Incorrect email or password.")
        if cfg.public_demo:
            st.caption("Owner / reviewer sign-in. Visitors don't need an account.")
            if st.button("← Back to the read-only demo", use_container_width=True):
                _enter_demo()
                st.rerun()
        else:
            st.caption("Demo users are created by `python -m scripts.seed` using PAYROLL_DEMO_PASSWORD.")


from ui.common import _boot  # noqa: E402

_boot()

if not user() and get_settings().public_demo and not st.session_state.get("owner_login"):
    _enter_demo()
if not user():
    login()
    st.stop()

P = st.Page
pages = {
    "Overview": [P(views_payroll.dashboard, title="Dashboard", icon="📊", url_path="dashboard", default=True)],
    "People": [],
    "Payroll": [],
    "Insight": [],
    "Compliance": [],
    "Admin": [],
}
if can(Perm.EMPLOYEE_READ):
    pages["People"] += [P(views_people.employees, title="Employees", icon="👥", url_path="employees"),
                        P(views_people.employee_profile, title="Employee Profile", icon="🪪", url_path="profile")]
if can(Perm.TAX_PROFILE_WRITE) or can(Perm.PAYROLL_READ):
    pages["People"].append(P(views_people.rpn, title="RPN / Tax Data", icon="🧾", url_path="rpn"))
if can(Perm.PAYROLL_READ):
    pages["Payroll"] += [P(views_payroll.calendar, title="Payroll Calendar", icon="🗓️", url_path="calendar"),
                         P(views_payroll.runs, title="Payroll Runs", icon="▶️", url_path="runs"),
                         P(views_payroll.calculation, title="Payroll Calculation", icon="🔎", url_path="calculation"),
                         P(views_payroll.exceptions, title="Exceptions", icon="🚩", url_path="exceptions"),
                         P(views_payroll.payslips, title="Payslips", icon="📄", url_path="payslips")]
if can(Perm.REPORTS):
    pages["Insight"].append(P(views_admin.reports, title="Reports", icon="📑", url_path="reports"))
if can(Perm.ANALYTICS):
    pages["Insight"].append(P(views_admin.analytics, title="Analytics", icon="📈", url_path="analytics"))
if can(Perm.RULES_READ):
    pages["Compliance"].append(P(views_admin.rules, title="Tax Rules", icon="⚖️", url_path="rules"))
if can(Perm.REVENUE_PREPARE) or can(Perm.REVENUE_READ):
    pages["Compliance"].append(P(views_admin.revenue, title="Revenue Submission", icon="🏛️", url_path="revenue"))
if can(Perm.AUDIT_READ):
    pages["Compliance"].append(P(views_admin.audit_log, title="Audit Log", icon="🕵️", url_path="audit"))
pages["Admin"].append(P(views_admin.settings, title="Settings", icon="⚙️", url_path="settings"))

with st.sidebar:
    u = user()
    if read_only():
        st.info("👀 **Read-only demo** — explore every page, filter, drill-down and download. "
                "Nothing can be changed or saved. All people and figures are synthetic.")
        if st.button("Owner sign in", use_container_width=True):
            st.session_state.clear()
            st.session_state.owner_login = True
            st.rerun()
    else:
        st.markdown(f"**{u['name']}**  \n<span class='small'>{u['role'].replace('_', ' ').title()}</span>", unsafe_allow_html=True)
        if st.button("Sign out", use_container_width=True):
            st.session_state.clear()
            st.rerun()

st.navigation({k: v for k, v in pages.items() if v}, expanded=True).run()
