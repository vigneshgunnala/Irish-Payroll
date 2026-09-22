"""Money helpers. All statutory arithmetic uses Decimal, never float."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def D(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    if isinstance(value, float):
        # go via str to avoid binary float artefacts (0.1 -> 0.1000000000000000055...)
        return Decimal(repr(value))
    return Decimal(str(value))


def money(value: Any) -> Decimal:
    """Round half-up to the cent (standard payroll rounding)."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def ceil_cent(value: Any) -> Decimal:
    """Round up to the next cent - Revenue's convention for periodised cut-offs/credits."""
    return D(value).quantize(CENT, rounding=ROUND_CEILING)


def fmt(value: Any) -> str:
    return f"€{money(value):,.2f}"


def pct(rate: Any) -> str:
    r = D(rate) * 100
    return f"{r.normalize():f}%"
