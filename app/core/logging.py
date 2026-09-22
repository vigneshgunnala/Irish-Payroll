"""Structured logging with a redaction filter so PPSNs and passwords never reach log output."""

from __future__ import annotations

import logging
import re

PPSN_RE = re.compile(r"\b\d{7}[A-W][A-IW]?\b", re.IGNORECASE)
SECRET_RE = re.compile(r"(password|secret|token)(\"?\s*[:=]\s*\"?)[^\s\",]+", re.IGNORECASE)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        msg = PPSN_RE.sub("[PPSN]", msg)
        msg = SECRET_RE.sub(r"\1\2[REDACTED]", msg)
        record.msg, record.args = msg, ()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
