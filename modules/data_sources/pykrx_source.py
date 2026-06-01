"""
modules/data_sources/pykrx_source.py — pykrx (한국거래소) 전담 소스

한국 종목의 수급 데이터:
- 외국인/기관 일별 순매수
- 공매도 잔고
- 일별 OHLCV 보조

CAN SLIM의 I(Institutional) 항목을 한국 종목에서 구현 가능하게 해줌.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from config import PYKRX_DEFAULT_LOOKBACK_DAYS


def is_pykrx_available() -> tuple[bool, str]:
    """pykrx 사용 가능 여부"""
    try:
        import pykrx  # noqa: F401
        return True, "OK"
    except ImportError:
        return False, "pykrx 패키지 미설치 (pip install pykrx)"


def _extract_korean_code(ticker: str) -> Optional[str]:
    upper = ticker.upper()
    if upper.endswith(".KS") or upper.endswith(".KQ"):
        return upper.split(".")[0]
    return None


def fetch_pykrx(ticker: str, lookback_days: int = PYKRX_DEFAULT_LOOKBACK_DAYS,
                verbose: bool = False) -> dict:
    """
    pykrx에서 한국 종목의 수급 데이터 수집.

    Returns:
        dict with keys:
            - investor_flow:  일별 외국인/기관/개인 순매수 DataFrame
            - short_selling:  일별 공매도 거래/잔고 DataFrame
            - foreign_holding: 외국인 보유 비중 시계열
    """
    empty_result = {
        "investor_flow":   pd.DataFrame(),
        "short_selling":   pd.DataFrame(),
        "foreign_holding": pd.DataFrame(),
    }

    # 1. 한국 종목인지
    code = _extract_korean_code(ticker)
    if code is None:
        if verbose:
            print(f"  [pykrx SKIP] {ticker}는 한국 종목이 아님")
        return empty_result

    # 2. pykrx 사용 가능 여부
    available, msg = is_pykrx_available()
    if not available:
        if verbose:
            print(f"  [pykrx SKIP] {msg}")
        return empty_result

    # 3. 기간 설정
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")

    result = empty_result.copy()

    # 외국인/기관 일별 순매수
    try:
        from pykrx import stock
        flow = stock.get_market_trading_value_by_date(start, end, code)
        if flow is not None and not flow.empty:
            result["investor_flow"] = flow
    except Exception as e:
        if verbose:
            print(f"  [pykrx WARN] investor_flow failed: {e}")

    # 공매도
    try:
        from pykrx import stock
        short = stock.get_shorting_status_by_date(start, end, code)
        if short is not None and not short.empty:
            result["short_selling"] = short
    except Exception as e:
        if verbose:
            print(f"  [pykrx WARN] short_selling failed: {e}")

    # 외국인 보유 비중
    try:
        from pykrx import stock
        foreign = stock.get_exhaustion_rates_of_foreign_investor(start, end, code)
        if foreign is not None and not foreign.empty:
            result["foreign_holding"] = foreign
    except Exception as e:
        if verbose:
            print(f"  [pykrx WARN] foreign_holding failed: {e}")

    return result


def get_investor_flow_summary(flow_df: pd.DataFrame, days: int = 20) -> dict:
    """
    외국인/기관 매매 흐름 요약. 최근 N일.

    Returns:
        {
            "foreign_net":         최근 N일 외국인 순매수 합계,
            "institutional_net":   최근 N일 기관 순매수 합계,
            "retail_net":          최근 N일 개인 순매수 합계,
            "foreign_buying_days": 외국인 매수일 수 / N,
        }
    """
    if flow_df is None or flow_df.empty:
        return {}

    recent = flow_df.tail(days)

    # pykrx 컬럼: '외국인합계', '기관합계', '개인', '전체' (금액 기준, 원)
    def _sum_col(col_name: str) -> float:
        if col_name in recent.columns:
            return float(recent[col_name].sum())
        return 0.0

    def _buying_days(col_name: str) -> int:
        if col_name in recent.columns:
            return int((recent[col_name] > 0).sum())
        return 0

    return {
        "foreign_net":         _sum_col("외국인합계"),
        "institutional_net":   _sum_col("기관합계"),
        "retail_net":          _sum_col("개인"),
        "foreign_buying_days": _buying_days("외국인합계") / max(len(recent), 1),
        "instit_buying_days":  _buying_days("기관합계") / max(len(recent), 1),
        "days_analyzed":       len(recent),
    }
