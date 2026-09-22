"""Shared Streamlit helpers: auth state, formatting, chart theme, badges."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
from sqlalchemy import select

from app.core.security import Perm, Role, has_perm
from app.db.base import SessionLocal
from app.db.models import Company, User

# Validated categorical palette (dataviz reference palette, light mode) - fixed order, never cycled
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQ_BLUE = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab"]
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
SEVERITY_ICON = {"INFO": "ℹ️ INFO", "WARNING": "⚠️ WARNING", "ERROR": "⛔ ERROR", "CRITICAL": "🛑 CRITICAL"}
RUN_BADGE = {"DRAFT": "⚪ Draft", "CALCULATING": "🔄 Calculating", "VALIDATION_REQUIRED": "🟠 Validation required",
             "READY_FOR_APPROVAL": "🔵 Ready for approval", "APPROVED": "🟢 Approved", "SUBMITTED": "📤 Submitted",
             "COMPLETED": "✅ Completed", "REVERSED": "↩️ Reversed"}

pio.templates["payroll"] = go.layout.Template(layout=go.Layout(
    font=dict(family="Inter, Segoe UI, sans-serif", size=13, color="#0b0b0b"),
    colorway=SERIES, plot_bgcolor="#fcfcfb", paper_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(showgrid=False, linecolor="#d4d4d0", ticks="outside", tickcolor="#d4d4d0"),
    yaxis=dict(gridcolor="#ecebe7", zeroline=False, linecolor="rgba(0,0,0,0)"),
    margin=dict(l=10, r=10, t=40, b=10), hoverlabel=dict(bgcolor="white", font_size=12),
    legend=dict(orientation="h", yanchor="top", y=-0.12, x=0, traceorder="normal"), bargap=0.25,
))
pio.templates.default = "payroll"


@st.cache_resource(show_spinner="Preparing the payroll database (first start builds the demo data - about a minute)…")
def _boot() -> bool:
    from app.services.bootstrap import ensure_ready

    ensure_ready()  # tables + rule sync; seeds demo data once when PAYROLL_AUTO_SEED=true
    return True


try:  # Streamlit control-flow exceptions (st.rerun / st.stop) must COMMIT, not roll back
    from streamlit.runtime.scriptrunner_utils.exceptions import RerunException, StopException
    _CONTROL_FLOW: tuple[type[BaseException], ...] = (RerunException, StopException)
except ImportError:  # pragma: no cover - older Streamlit
    _CONTROL_FLOW = ()


def read_only() -> bool:
    u = st.session_state.get("user")
    return bool(u and u["role"] == Role.DEMO_VIEWER.value)


@contextmanager
def db():
    """One DB session per block. For the read-only demo visitor nothing is ever committed (belt and braces:
    the role also has no write permissions, so the write buttons are not shown at all)."""
    _boot()
    s = SessionLocal()
    # read-only: never commit - close() below discards any pending change (rollback() would expire loaded rows)
    finish = (lambda: None) if read_only() else s.commit
    try:
        yield s
        finish()
    except _CONTROL_FLOW:
        finish()
        raise
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def eur(v: Any, dp: int = 2) -> str:
    try:
        return f"€{Decimal(str(v)):,.{dp}f}"
    except Exception:  # noqa: BLE001
        return "—"


def user() -> dict | None:
    return st.session_state.get("user")


def can(perm: Perm) -> bool:
    u = user()
    return bool(u and has_perm(u["role"], perm))


def guard(perm: Perm) -> None:
    if not can(perm):
        st.error(f"Your role does not have access to this page ({perm.value}).")
        st.stop()


def current_user_obj(s):
    u = user()
    return s.get(User, u["user_id"]) if u else None


def company_id() -> int:
    if "company_id" not in st.session_state:
        with db() as s:
            co = s.scalar(select(Company).order_by(Company.company_id))
            st.session_state.company_id = co.company_id if co else None
    return st.session_state.company_id


def kpi(col, label: str, value: str, delta: str | None = None, help: str | None = None) -> None:
    col.metric(label, value, delta, help=help, border=True, delta_color="off")


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(f"## {title}")
    if subtitle:
        st.caption(subtitle)


def style_fig(fig: go.Figure, height: int = 340, title: str | None = None) -> go.Figure:
    fig.update_layout(height=height, title=dict(text=title or "", font=dict(size=15), x=0.01, xanchor="left") if title else None)
    fig.update_traces(selector=dict(type="bar"), marker_line_width=0, cliponaxis=False)
    fig.update_layout(margin=dict(l=50, r=70, t=50, b=10))
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    return fig
