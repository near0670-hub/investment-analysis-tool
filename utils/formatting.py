"""
utils/formatting.py — 숫자, 통화, 퍼센트 포맷팅

한국/미국 통화 단위 차이 처리.
한국: 원, 억, 조
미국: $, M, B
"""

from typing import Optional, Union

Number = Union[int, float, None]


def format_number(value: Number, decimals: int = 2) -> str:
    """일반 숫자 포맷 (천 단위 콤마)"""
    if value is None or _is_nan(value):
        return "—"
    return f"{value:,.{decimals}f}"


def format_pct(value: Number, decimals: int = 1, with_sign: bool = False) -> str:
    """0.25 → '25.0%' 형태"""
    if value is None or _is_nan(value):
        return "—"
    pct = value * 100
    if with_sign and pct > 0:
        return f"+{pct:.{decimals}f}%"
    return f"{pct:.{decimals}f}%"


def format_currency(value: Number, currency: str = "USD", decimals: int = 2) -> str:
    """
    통화 포맷
    - USD: $1,234.56, $1.23M, $1.23B, $1.23T
    - KRW: 1,234원, 1,234억원, 1.23조원
    """
    if value is None or _is_nan(value):
        return "—"

    if currency == "USD":
        return _format_usd(value, decimals)
    elif currency == "KRW":
        return _format_krw(value)
    else:
        return f"{value:,.{decimals}f} {currency}"


def _format_usd(value: float, decimals: int = 2) -> str:
    abs_v = abs(value)
    sign = "-" if value < 0 else ""
    if abs_v >= 1e12:
        return f"{sign}${abs_v / 1e12:.{decimals}f}T"
    if abs_v >= 1e9:
        return f"{sign}${abs_v / 1e9:.{decimals}f}B"
    if abs_v >= 1e6:
        return f"{sign}${abs_v / 1e6:.{decimals}f}M"
    if abs_v >= 1e3:
        return f"{sign}${abs_v / 1e3:.{decimals}f}K"
    return f"{sign}${abs_v:,.{decimals}f}"


def _format_krw(value: float) -> str:
    """한국 원화: 억/조 단위"""
    abs_v = abs(value)
    sign = "-" if value < 0 else ""
    if abs_v >= 1e12:
        return f"{sign}{abs_v / 1e12:.2f}조원"
    if abs_v >= 1e8:
        return f"{sign}{abs_v / 1e8:,.0f}억원"
    if abs_v >= 1e4:
        return f"{sign}{abs_v / 1e4:,.0f}만원"
    return f"{sign}{abs_v:,.0f}원"


def format_multiple(value: Number, decimals: int = 1) -> str:
    """PER, PBR 등 배수 → '38.0배' / '38.0x'"""
    if value is None or _is_nan(value):
        return "—"
    return f"{value:.{decimals}f}x"


def format_yoy(value: Number, decimals: int = 1) -> str:
    """YoY 성장률 → '+25.0%' / '-12.5%' (부호 강제)"""
    if value is None or _is_nan(value):
        return "—"
    return format_pct(value, decimals=decimals, with_sign=True)


def format_verdict(verdict: str, value: Optional[float] = None,
                   threshold: Optional[float] = None) -> str:
    """체크리스트 출력: '✓ 12.5% (기준 17%)' 형태"""
    parts = [verdict]
    if value is not None:
        parts.append(format_pct(value))
    if threshold is not None:
        parts.append(f"(기준 {format_pct(threshold)})")
    return " ".join(parts)


def _is_nan(value) -> bool:
    """NaN 체크 (pandas/numpy 의존성 없이)"""
    try:
        return value != value  # NaN의 유일한 특성
    except Exception:
        return False
