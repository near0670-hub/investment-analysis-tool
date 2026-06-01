"""
modules/data_sources/yfinance_source.py — yfinance 전담 소스

미국 종목의 모든 데이터 + 한국 종목의 기본 정보(가격, 시총, 섹터).
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import yfinance as yf


def fetch_yfinance(ticker: str, verbose: bool = False) -> dict:
    """
    yfinance로 원시 데이터 수집.

    Returns:
        dict: yfinance 원시 데이터 (정규화 전)
              data_loader.py가 이걸 표준 스키마로 변환
    """
    yf_ticker = yf.Ticker(ticker)

    def _safe_attr(name: str, default=None, call: bool = False, **kwargs):
        try:
            attr = getattr(yf_ticker, name)
            if call:
                return attr(**kwargs)
            return attr
        except Exception as e:
            if verbose:
                print(f"  [WARN] yfinance.{name} failed for {ticker}: {e}")
            return default

    return {
        "info":               _safe_attr("info", {}) or {},
        "price":              _safe_attr("history", pd.DataFrame(), call=True, period="5y"),
        "income_quarterly":   _safe_attr("quarterly_financials", pd.DataFrame()),
        "income_annual":      _safe_attr("financials", pd.DataFrame()),
        "balance_quarterly":  _safe_attr("quarterly_balance_sheet", pd.DataFrame()),
        "balance_annual":     _safe_attr("balance_sheet", pd.DataFrame()),
        "cashflow_quarterly": _safe_attr("quarterly_cashflow", pd.DataFrame()),
        "cashflow_annual":    _safe_attr("cashflow", pd.DataFrame()),
        "earnings_dates":     _safe_attr("earnings_dates", None),
        "dividends":          _safe_attr("dividends", pd.Series(dtype=float)),
        "recommendations":    _safe_attr("recommendations", None),
    }
