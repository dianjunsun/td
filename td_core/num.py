"""金额与价格的定点四舍五入。"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

EPS = Decimal("0.0001")
PATH_LOSS = Decimal("0.1375")


def D(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quant(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def money(value: Decimal) -> Decimal:
    return quant(value, "0.01")


def px(value: Decimal) -> Decimal:
    return quant(value, "0.0001")


def shares_q(value: Decimal) -> Decimal:
    return quant(value, "0.0001")


def store_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")
