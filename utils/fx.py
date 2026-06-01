"""
utils/fx.py — 환율 처리

USD ↔ KRW 변환.
yfinance에서 KRW=X 티커로 실시간 환율 조회.
캐싱하여 호출 빈도 최소화.
"""

from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

# 메모리 캐시 (Streamlit 세션 동안 유지)
_FX_CACHE = {"rate": None, "timestamp": None}
_FX_CACHE_TTL_MINUTES = 60


def get_usd_krw_rate() -> Optional[float]:
    """
    USD/KRW 환율 조회 (1 USD = ? KRW)

    Returns:
        환율 (예: 1378.50) 또는 None (조회 실패 시)
    """
    # 캐시 유효성 검사
    if _FX_CACHE["rate"] is not None and _FX_CACHE["timestamp"] is not None:
        elapsed = datetime.now() - _FX_CACHE["timestamp"]
        if elapsed < timedelta(minutes=_FX_CACHE_TTL_MINUTES):
            return _FX_CACHE["rate"]

    # 새로 조회
    try:
        ticker = yf.Ticker("KRW=X")
        hist = ticker.history(period="1d")
        if hist.empty:
            return _FX_CACHE["rate"]  # 실패 시 이전 캐시 반환

        rate = float(hist["Close"].iloc[-1])
        _FX_CACHE["rate"] = rate
        _FX_CACHE["timestamp"] = datetime.now()
        return rate
    except Exception:
        return _FX_CACHE["rate"]


def convert_usd_to_krw(usd_amount: float) -> Optional[float]:
    rate = get_usd_krw_rate()
    if rate is None:
        return None
    return usd_amount * rate


def convert_krw_to_usd(krw_amount: float) -> Optional[float]:
    rate = get_usd_krw_rate()
    if rate is None or rate == 0:
        return None
    return krw_amount / rate


def detect_currency_from_ticker(ticker: str) -> str:
    """티커 접미사로 통화 추정"""
    ticker_upper = ticker.upper()
    if ticker_upper.endswith(".KS") or ticker_upper.endswith(".KQ"):
        return "KRW"
    if ticker_upper.endswith(".T"):
        return "JPY"
    if ticker_upper.endswith(".HK"):
        return "HKD"
    if ticker_upper.endswith(".L"):
        return "GBP"
    # 기본값: USD (미국 종목)
    return "USD"
