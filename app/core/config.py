"""Application configuration - everything secret comes from the environment."""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("payroll.config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PAYROLL_", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./payroll.db"
    secret_key: str = ""
    access_token_minutes: int = 60
    log_level: str = "INFO"
    # bootstrap admin (only used by scripts/seed.py; never hard-coded)
    admin_email: str = "admin@example.ie"
    admin_password: str = ""

    def effective_secret(self) -> str:
        if self.secret_key:
            return self.secret_key
        if self.env == "production":
            raise RuntimeError("PAYROLL_SECRET_KEY must be set in production")
        # dev/test: ephemeral per-process key, tokens die on restart
        key = secrets.token_urlsafe(48)
        object.__setattr__(self, "secret_key", key)
        log.warning("PAYROLL_SECRET_KEY not set - using an ephemeral development key")
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
