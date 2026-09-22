"""FastAPI application. OpenAPI docs at /docs."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api.routers import admin, core, payroll
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import get_engine, init_db

settings = get_settings()
configure_logging(settings.log_level)



@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Irish Payroll Management & Compliance System",
    version="1.0.0",
    description="Portfolio prototype. Statutory values are versioned rules with official sources; "
                "unverified rules are blocked from calculation. Not certified payroll software.",
)
app.include_router(core.router)
app.include_router(payroll.router)
app.include_router(admin.router)


@app.get("/health", tags=["system"])
def health():
    with get_engine().connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok", "database": get_engine().dialect.name}
