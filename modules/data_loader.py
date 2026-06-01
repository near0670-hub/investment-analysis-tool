"""
modules/data_loader.py — 멀티 소스 라우팅 + 표준 스키마 통합

라우팅 정책:
  US 종목  → yfinance만
  KR 종목  → yfinance (가격/시총/기본정보) + DART (재무제표 보강) + pykrx (수급)
  기타     → yfinance만

표준 출력 스키마 (Analysis Layer가 사용):
{
    "meta": {
        ticker, name, country, currency,
        sector_yf, industry_yf, sector_internal,
        market_cap, exchange, fetched_at,
    },
    "info": dict,
    "price": DataFrame,
    "income_quarterly":  DataFrame,
    "income_annual":     DataFrame,
    "balance_quarterly": DataFrame,
    "balance_annual":    DataFrame,
    "cashflow_quarterly": DataFrame,
    "cashflow_annual":    DataFrame,
    "earnings_dates":    DataFrame or None,
    "dividends":         Series,
    "shares_outstanding": float or None,
    "recommendations":   DataFrame or None,

    # 한국 종목 전용 (다른 종목은 빈 DataFrame)
    "kr_filings":         DataFrame,    # DART 최근 공시 목록
    "kr_investor_flow":   DataFrame,    # pykrx 외국인/기관 일별 순매수
    "kr_short_selling":   DataFrame,    # 공매도
    "kr_foreign_holding": DataFrame,    # 외국인 보유 비중

    "data_quality": dict,
    "data_sources": list[str],          # 사용된 소스 목록 (디버깅용)
}
"""

from __future__ import annotations

import pickle
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from config import CACHE_DIR, CACHE_TTL_HOURS, KOREA_TICKER_SUFFIXES
from modules.sector_classifier import classify_sector
from utils.validation import calculate_data_quality, validate_ticker


# ============================================================
# 캐싱
# ============================================================
def _cache_path(ticker: str) -> Path:
    safe_ticker = ticker.replace(".", "_").replace("=", "_")
    return CACHE_DIR / f"{safe_ticker}.pkl"


def _is_cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age < timedelta(hours=CACHE_TTL_HOURS)


def _load_cache(ticker: str) -> Optional[dict]:
    path = _cache_path(ticker)
    if not _is_cache_fresh(path):
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _save_cache(ticker: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(ticker)
    try:
        with open(path, "wb") as f:
            pickle.dump(data, f)
    except Exception:
        pass


# ============================================================
# Country / Currency
# ============================================================
def _detect_country_currency(ticker: str) -> tuple[str, str]:
    upper = ticker.upper()
    if upper.endswith(KOREA_TICKER_SUFFIXES):
        return "KR", "KRW"
    if upper.endswith(".T"):
        return "JP", "JPY"
    if upper.endswith(".HK"):
        return "HK", "HKD"
    if upper.endswith(".L"):
        return "UK", "GBP"
    return "US", "USD"


# ============================================================
# 재무제표 병합 (yfinance + DART)
# ============================================================
def _merge_financial_statements(
    yf_df: pd.DataFrame,
    dart_df: pd.DataFrame,
    prefer: str = "dart",
) -> pd.DataFrame:
    """
    yfinance와 DART의 동일 항목 DataFrame을 병합.

    한국 종목의 경우 DART가 더 정확하므로 prefer="dart" (기본).
    DART에 없는 항목은 yfinance 값 유지.

    행 = 항목명, 열 = 날짜.
    """
    if yf_df is None or yf_df.empty:
        return dart_df if dart_df is not None else pd.DataFrame()
    if dart_df is None or dart_df.empty:
        return yf_df

    if prefer == "dart":
        # DART를 베이스로, yfinance는 DART에 없는 행만 추가
        merged = dart_df.copy()
        for row_idx in yf_df.index:
            if row_idx not in merged.index:
                # 컬럼이 다르면 reindex
                yf_row = yf_df.loc[[row_idx]].reindex(columns=merged.columns)
                merged = pd.concat([merged, yf_row])
        return merged
    else:
        # yfinance 우선
        merged = yf_df.copy()
        for row_idx in dart_df.index:
            if row_idx not in merged.index:
                dart_row = dart_df.loc[[row_idx]].reindex(columns=merged.columns)
                merged = pd.concat([merged, dart_row])
        return merged


# ============================================================
# 메인 로더
# ============================================================
def load_company_data(
    ticker: str,
    use_cache: bool = True,
    verbose: bool = False,
    use_dart: bool = True,
    use_pykrx: bool = True,
) -> dict:
    """
    Ticker → 표준화된 회사 데이터 dict.

    Args:
        ticker:    종목 코드
        use_cache: 캐시 사용
        verbose:   진행 로깅
        use_dart:  한국 종목 시 DART 사용 여부 (API 키 없으면 자동 스킵)
        use_pykrx: 한국 종목 시 pykrx 사용 여부 (미설치 시 자동 스킵)

    Returns:
        표준 스키마 dict

    Raises:
        ValueError: ticker 검증 실패
    """
    # 1. 검증
    valid, msg = validate_ticker(ticker)
    if not valid:
        raise ValueError(f"Ticker 검증 실패: {msg}")
    ticker = ticker.strip().upper()

    # 2. 캐시 확인
    if use_cache:
        cached = _load_cache(ticker)
        if cached is not None:
            if verbose:
                print(f"[Cache HIT] {ticker}")
            return cached

    if verbose:
        print(f"[Fetching] {ticker}")

    country, currency = _detect_country_currency(ticker)
    sources_used = []

    # ============================================================
    # 3. yfinance (모든 종목 공통)
    # ============================================================
    from modules.data_sources.yfinance_source import fetch_yfinance
    yf_data = fetch_yfinance(ticker, verbose=verbose)
    sources_used.append("yfinance")

    info = yf_data.get("info", {})

    # ============================================================
    # 4. 한국 종목이면 DART + pykrx 추가
    # ============================================================
    dart_data = {}
    pykrx_data = {}

    if country == "KR":
        if use_dart:
            try:
                from modules.data_sources.dart_source import fetch_dart, is_dart_available
                available, dart_msg = is_dart_available()
                if available:
                    dart_data = fetch_dart(ticker, verbose=verbose)
                    sources_used.append("dart")
                elif verbose:
                    print(f"  [DART unavailable] {dart_msg}")
            except Exception as e:
                if verbose:
                    print(f"  [DART error] {e}")

        if use_pykrx:
            try:
                from modules.data_sources.pykrx_source import fetch_pykrx, is_pykrx_available
                available, pykrx_msg = is_pykrx_available()
                if available:
                    pykrx_data = fetch_pykrx(ticker, verbose=verbose)
                    sources_used.append("pykrx")
                elif verbose:
                    print(f"  [pykrx unavailable] {pykrx_msg}")
            except Exception as e:
                if verbose:
                    print(f"  [pykrx error] {e}")

    # ============================================================
    # 5. 재무제표 병합 (한국 종목은 DART 우선)
    # ============================================================
    prefer_source = "dart" if country == "KR" and dart_data else "yfinance"

    income_quarterly = _merge_financial_statements(
        yf_data.get("income_quarterly", pd.DataFrame()),
        dart_data.get("income_quarterly", pd.DataFrame()),
        prefer=prefer_source,
    )
    income_annual = _merge_financial_statements(
        yf_data.get("income_annual", pd.DataFrame()),
        dart_data.get("income_annual", pd.DataFrame()),
        prefer=prefer_source,
    )
    balance_quarterly = _merge_financial_statements(
        yf_data.get("balance_quarterly", pd.DataFrame()),
        dart_data.get("balance_quarterly", pd.DataFrame()),
        prefer=prefer_source,
    )
    balance_annual = _merge_financial_statements(
        yf_data.get("balance_annual", pd.DataFrame()),
        dart_data.get("balance_annual", pd.DataFrame()),
        prefer=prefer_source,
    )
    cashflow_quarterly = _merge_financial_statements(
        yf_data.get("cashflow_quarterly", pd.DataFrame()),
        dart_data.get("cashflow_quarterly", pd.DataFrame()),
        prefer=prefer_source,
    )
    cashflow_annual = _merge_financial_statements(
        yf_data.get("cashflow_annual", pd.DataFrame()),
        dart_data.get("cashflow_annual", pd.DataFrame()),
        prefer=prefer_source,
    )

    # ============================================================
    # 6. 메타 정보
    # ============================================================
    yf_sector = info.get("sector")
    yf_industry = info.get("industry")
    sector_internal = classify_sector(ticker, yf_sector, yf_industry)
    name = info.get("longName") or info.get("shortName") or ticker

    meta = {
        "ticker": ticker,
        "name": name,
        "country": country,
        "currency": currency,
        "sector_yf": yf_sector,
        "industry_yf": yf_industry,
        "sector_internal": sector_internal,
        "market_cap": info.get("marketCap"),
        "exchange": info.get("exchange"),
        "fetched_at": datetime.now().isoformat(),
    }

    # ============================================================
    # 7. 데이터 품질 평가
    # ============================================================
    data_quality = {
        "income_quarterly":   calculate_data_quality(income_quarterly),
        "income_annual":      calculate_data_quality(income_annual),
        "balance_quarterly":  calculate_data_quality(balance_quarterly),
        "balance_annual":     calculate_data_quality(balance_annual),
        "cashflow_quarterly": calculate_data_quality(cashflow_quarterly),
        "cashflow_annual":    calculate_data_quality(cashflow_annual),
    }

    # ============================================================
    # 8. 결과 조립
    # ============================================================
    result = {
        "meta": meta,
        "info": info,
        "price":              yf_data.get("price", pd.DataFrame()),
        "income_quarterly":   income_quarterly,
        "income_annual":      income_annual,
        "balance_quarterly":  balance_quarterly,
        "balance_annual":     balance_annual,
        "cashflow_quarterly": cashflow_quarterly,
        "cashflow_annual":    cashflow_annual,
        "earnings_dates":     yf_data.get("earnings_dates"),
        "dividends":          yf_data.get("dividends", pd.Series(dtype=float)),
        "shares_outstanding": info.get("sharesOutstanding"),
        "recommendations":    yf_data.get("recommendations"),

        # 한국 전용
        "kr_filings":         dart_data.get("recent_filings", pd.DataFrame()),
        "kr_investor_flow":   pykrx_data.get("investor_flow", pd.DataFrame()),
        "kr_short_selling":   pykrx_data.get("short_selling", pd.DataFrame()),
        "kr_foreign_holding": pykrx_data.get("foreign_holding", pd.DataFrame()),

        "data_quality": data_quality,
        "data_sources": sources_used,
    }

    if use_cache:
        _save_cache(ticker, result)

    return result


def load_multiple_companies(
    tickers: list[str],
    use_cache: bool = True,
    verbose: bool = False,
    delay_sec: float = 0.3,
    use_dart: bool = True,
    use_pykrx: bool = True,
) -> dict[str, dict]:
    """
    여러 종목 일괄 로드 (Peer Comparison용).

    실패한 ticker는 결과에서 제외 + 경고.
    """
    results = {}
    for i, ticker in enumerate(tickers):
        try:
            results[ticker] = load_company_data(
                ticker,
                use_cache=use_cache,
                verbose=verbose,
                use_dart=use_dart,
                use_pykrx=use_pykrx,
            )
        except Exception as e:
            if verbose:
                print(f"  [SKIP] {ticker}: {e}")
            continue
        if i < len(tickers) - 1:
            time.sleep(delay_sec)
    return results


def clear_cache(ticker: Optional[str] = None) -> int:
    """캐시 삭제. ticker=None이면 전체."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if ticker:
        path = _cache_path(ticker.strip().upper())
        if path.exists():
            path.unlink()
            return 1
        return 0

    count = 0
    for f in CACHE_DIR.glob("*.pkl"):
        f.unlink()
        count += 1
    return count


# ============================================================
# 데이터 소스 상태 진단 (UI에서 사용)
# ============================================================
def check_data_sources_status() -> dict:
    """
    각 데이터 소스의 사용 가능 여부 진단.
    Streamlit 사이드바에 표시하면 좋음.
    """
    status = {
        "yfinance": {"available": True, "message": "OK (기본 설치)"},
        "dart": {"available": False, "message": "확인 중..."},
        "pykrx": {"available": False, "message": "확인 중..."},
    }

    try:
        from modules.data_sources.dart_source import is_dart_available
        ok, msg = is_dart_available()
        status["dart"]["available"] = ok
        status["dart"]["message"] = msg
    except Exception as e:
        status["dart"]["message"] = f"모듈 로드 실패: {e}"

    try:
        from modules.data_sources.pykrx_source import is_pykrx_available
        ok, msg = is_pykrx_available()
        status["pykrx"]["available"] = ok
        status["pykrx"]["message"] = msg
    except Exception as e:
        status["pykrx"]["message"] = f"모듈 로드 실패: {e}"

    return status
