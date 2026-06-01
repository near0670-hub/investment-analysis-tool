"""
utils/validation.py — 입력 검증 + 결측치 처리

- Ticker 형식 검증
- DataFrame 결측치 정책 (skip / fill / warn)
- 안전 나눗셈 / CAGR 계산 헬퍼
"""

import re
from typing import Optional, Union

import numpy as np
import pandas as pd

# Ticker 패턴 (영문/숫자 + 옵션 접미사)
TICKER_PATTERN = re.compile(r"^[A-Z0-9]{1,7}(\.[A-Z]{1,3})?$")


def validate_ticker(ticker: str) -> tuple[bool, str]:
    """
    Ticker 형식 검증.

    Returns:
        (is_valid, message)
    """
    if not ticker:
        return False, "Ticker가 비어있습니다."

    ticker = ticker.strip().upper()

    if len(ticker) > 12:
        return False, f"Ticker가 너무 깁니다: {ticker}"

    if not TICKER_PATTERN.match(ticker):
        return False, f"Ticker 형식이 올바르지 않습니다: {ticker}"

    return True, "OK"


def safe_divide(numerator: Union[float, None],
                denominator: Union[float, None],
                default: Optional[float] = None) -> Optional[float]:
    """
    안전 나눗셈. 0/None 처리.

    >>> safe_divide(100, 50)   # 2.0
    >>> safe_divide(100, 0)    # None
    >>> safe_divide(None, 50)  # None
    """
    if numerator is None or denominator is None:
        return default
    if _is_nan(numerator) or _is_nan(denominator):
        return default
    if denominator == 0:
        return default
    return numerator / denominator


def safe_growth(current: Union[float, None],
                previous: Union[float, None]) -> Optional[float]:
    """
    YoY 성장률. 분모가 0이거나 음수면 None.

    음수에서 양수로 전환 (적자→흑자)은 별도 처리 필요.

    >>> safe_growth(120, 100)   # 0.2
    >>> safe_growth(80, 100)    # -0.2
    >>> safe_growth(100, 0)     # None
    >>> safe_growth(100, -50)   # None (음수 기준은 의미 없음)
    """
    if current is None or previous is None:
        return None
    if _is_nan(current) or _is_nan(previous):
        return None
    if previous <= 0:
        return None
    return (current - previous) / previous


def safe_cagr(end_value: Union[float, None],
              start_value: Union[float, None],
              years: int) -> Optional[float]:
    """
    CAGR 계산. n년 동안의 연평균 복리 성장률.

    >>> safe_cagr(100, 50, 2)   # ~0.414 (41.4%)
    """
    if end_value is None or start_value is None:
        return None
    if _is_nan(end_value) or _is_nan(start_value):
        return None
    if start_value <= 0 or end_value <= 0:
        return None
    if years <= 0:
        return None
    return (end_value / start_value) ** (1 / years) - 1


def safe_get(df: pd.DataFrame, row_label: str,
             col_index: int = 0) -> Optional[float]:
    """
    DataFrame에서 안전하게 값 추출. 행/열이 없거나 NaN이면 None.
    yfinance 재무제표 접근 시 자주 사용.
    """
    if df is None or df.empty:
        return None
    if row_label not in df.index:
        return None
    if col_index >= len(df.columns):
        return None
    try:
        value = df.loc[row_label].iloc[col_index]
        if _is_nan(value):
            return None
        return float(value)
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def calculate_data_quality(df: pd.DataFrame) -> float:
    """
    DataFrame의 결측치 비율 (0.0 ~ 1.0).
    1.0 = 모두 결측, 0.0 = 결측 없음.
    """
    if df is None or df.empty:
        return 1.0
    total = df.size
    if total == 0:
        return 1.0
    missing = df.isna().sum().sum()
    return float(missing / total)


def _is_nan(value) -> bool:
    """NaN 안전 체크"""
    if value is None:
        return True
    try:
        return bool(np.isnan(value))
    except (TypeError, ValueError):
        return False


def check_forward_data_availability(estimates_df: Optional[pd.DataFrame]) -> dict:
    """
    Forward EPS / 컨센서스 데이터 가용성 체크.
    한국 종목은 대부분 없음 → 수동 입력 유도.
    """
    if estimates_df is None or estimates_df.empty:
        return {
            "available": False,
            "reason": "Forward 추정치 데이터 없음 (한국 종목은 수동 입력 권장)",
        }

    quality = calculate_data_quality(estimates_df)
    if quality > 0.7:
        return {
            "available": False,
            "reason": f"Forward 데이터 결측치 비율 {quality:.0%} - 신뢰도 낮음",
        }

    return {"available": True, "quality": 1.0 - quality}
