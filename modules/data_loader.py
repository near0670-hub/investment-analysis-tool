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
    date_tolerance_days: int = 15,
) -> pd.DataFrame:
    """
    yfinance + DART 재무제표를 똑똑하게 병합.

    개선 사항 (v2):
    1. 분기 날짜 매칭: ±15일 이내면 같은 분기로 인식
       (DART가 분기말 30일, yfinance가 31일 같은 경우 같은 분기로 처리)
    2. 컬럼 통합: 같은 분기는 하나의 컬럼으로 합침 (분기 수가 두 배 되는 문제 해결)
    3. NaN 채우기: 한 소스에 값이 없으면 다른 소스 값으로 자동 fill
    4. 우선순위: prefer="dart"면 한국 종목에서 DART 값 우선 (더 정확)

    행 = 항목명, 열 = 분기말 날짜 (최신 → 과거 순)
    """
    # Empty handling
    if yf_df is None or yf_df.empty:
        return dart_df.copy() if dart_df is not None and not dart_df.empty else pd.DataFrame()
    if dart_df is None or dart_df.empty:
        return yf_df.copy()

    # 1. 우선/보조 소스 결정
    primary_df = dart_df if prefer == "dart" else yf_df
    secondary_df = yf_df if prefer == "dart" else dart_df

    primary_cols = list(primary_df.columns)
    secondary_cols = list(secondary_df.columns)

    # 2. 컬럼 매칭: 각 primary 컬럼에 대해 가장 가까운 secondary 컬럼 찾기
    tolerance = pd.Timedelta(days=date_tolerance_days)
    column_mapping: dict = {}  # primary_col → secondary_col (없으면 None)
    used_secondary = set()

    for p_col in primary_cols:
        try:
            p_ts = pd.Timestamp(p_col)
        except (TypeError, ValueError):
            column_mapping[p_col] = None
            continue

        best_match = None
        best_diff = tolerance
        for s_col in secondary_cols:
            if s_col in used_secondary:
                continue
            try:
                s_ts = pd.Timestamp(s_col)
            except (TypeError, ValueError):
                continue
            diff = abs(p_ts - s_ts)
            if diff <= best_diff:
                best_match = s_col
                best_diff = diff

        column_mapping[p_col] = best_match
        if best_match is not None:
            used_secondary.add(best_match)

    # 3. 매칭 안 된 secondary 컬럼 (한쪽 소스에만 있는 분기)
    unmatched_secondary = [c for c in secondary_cols if c not in used_secondary]

    # 4. 최종 컬럼: primary 컬럼 + 매칭 안 된 secondary 컬럼, 최신순 정렬
    all_columns = list(primary_cols) + unmatched_secondary

    def _sort_key(c):
        try:
            return pd.Timestamp(c)
        except (TypeError, ValueError):
            return pd.Timestamp("1900-01-01")

    all_columns = sorted(set(all_columns), key=_sort_key, reverse=True)

    # 5. 모든 행(항목) 수집 — 양쪽 union
    all_rows = list(dict.fromkeys(list(primary_df.index) + list(secondary_df.index)))

    # 6. 결과 DataFrame 빌드
    merged = pd.DataFrame(index=all_rows, columns=all_columns, dtype=float)

    # 6-1. primary 값 채우기
    for p_col in primary_cols:
        if p_col not in merged.columns:
            continue
        for row in primary_df.index:
            try:
                val = primary_df.at[row, p_col]
                if pd.notna(val):
                    merged.at[row, p_col] = float(val)
            except (KeyError, ValueError, TypeError):
                pass

    # 6-2. secondary로 NaN 채우기 (매칭된 컬럼)
    for primary_col, secondary_col in column_mapping.items():
        if secondary_col is None or primary_col not in merged.columns:
            continue
        for row in secondary_df.index:
            if row not in merged.index:
                continue
            try:
                # primary가 NaN인 경우에만 secondary 값 사용
                if pd.isna(merged.at[row, primary_col]):
                    val = secondary_df.at[row, secondary_col]
                    if pd.notna(val):
                        merged.at[row, primary_col] = float(val)
            except (KeyError, ValueError, TypeError):
                pass

    # 6-3. 매칭 안 된 secondary 컬럼 — 그대로 추가
    for s_col in unmatched_secondary:
        if s_col not in merged.columns:
            continue
        for row in secondary_df.index:
            try:
                val = secondary_df.at[row, s_col]
                if pd.notna(val):
                    merged.at[row, s_col] = float(val)
            except (KeyError, ValueError, TypeError):
                pass

    return merged


def _fix_q4_cumulative_to_quarterly(
    quarterly_df: pd.DataFrame,
    annual_df: pd.DataFrame,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    한국 종목: Q4 분기 컬럼에 들어있는 연간 누적값을 진짜 분기값으로 변환.

    DART 사업보고서(11011)는 연간 누적값을 보고하는데, 우리 병합 로직이
    분기말 날짜(예: 2024-12-30)와 연간 마지막 날짜(2024-12-31)를 ±15일 매칭하면서
    연간 누적값이 4분기 자리에 들어오는 버그.

    예시 (삼성전자):
        Q1: 71.9조, Q2: 74.1조, Q3: 79.1조, Q4 자리: 300.9조 (연간 누적)
        → 정상화: Q4 = 300.9 - (71.9 + 74.1 + 79.1) = 75.8조

    이 변환은 flow 항목(매출, 영업이익, 순이익 등)에만 적용.
    stock 항목(자산, 부채, 자본 등)은 분기말 시점값이므로 누적이 아님.
    → balance sheet에는 이 함수를 적용하지 않음 (호출 측에서 제외).
    """
    if quarterly_df is None or quarterly_df.empty:
        return quarterly_df
    if annual_df is None or annual_df.empty:
        # 연간 데이터 없으면 보정 불가
        return quarterly_df

    # 분기 컬럼을 연도별로 그룹핑
    # 컬럼은 보통 pd.Timestamp
    quarterly_cols = list(quarterly_df.columns)
    annual_cols = list(annual_df.columns)

    fixed_df = quarterly_df.copy()
    n_fixes = 0

    # 연도별로 처리
    years_processed = set()
    for q_col in quarterly_cols:
        try:
            q_ts = pd.Timestamp(q_col)
        except (TypeError, ValueError):
            continue

        year = q_ts.year
        if year in years_processed:
            continue

        # 해당 연도의 모든 분기 찾기
        year_quarters = []
        for c in quarterly_cols:
            try:
                c_ts = pd.Timestamp(c)
                if c_ts.year == year:
                    year_quarters.append((c, c_ts))
            except (TypeError, ValueError):
                continue

        # 4개 분기가 다 있어야 보정 가능
        if len(year_quarters) < 4:
            continue

        # 분기 정렬 (시간순)
        year_quarters.sort(key=lambda x: x[1])
        q1_col, q2_col, q3_col, q4_col = [c for c, _ in year_quarters[:4]]

        # 해당 연도의 연간 컬럼 찾기 (±15일 이내)
        annual_col = None
        for a_col in annual_cols:
            try:
                a_ts = pd.Timestamp(a_col)
                if a_ts.year == year:
                    annual_col = a_col
                    break
            except (TypeError, ValueError):
                continue

        if annual_col is None:
            continue

        # 각 행(항목)에 대해 Q4 보정
        for row in fixed_df.index:
            try:
                q1_val = fixed_df.at[row, q1_col]
                q2_val = fixed_df.at[row, q2_col]
                q3_val = fixed_df.at[row, q3_col]
                q4_val = fixed_df.at[row, q4_col]
                annual_val = annual_df.at[row, annual_col] if row in annual_df.index else None

                # Q1, Q2, Q3, annual은 반드시 있어야 함 (보정의 입력값)
                if any(pd.isna(v) for v in [q1_val, q2_val, q3_val, annual_val]):
                    continue

                q1_val = float(q1_val); q2_val = float(q2_val)
                q3_val = float(q3_val)
                annual_val = float(annual_val)
                q123_sum = q1_val + q2_val + q3_val

                # 케이스 1: Q4가 NaN — DART가 Q4 분기 데이터를 안 줄 때
                # (예: SK하이닉스 EPS, 한국 기업의 분기 EPS는 흔히 4Q 빠짐)
                # → 연간 - Q1Q2Q3 = Q4 분기값으로 채움
                if pd.isna(q4_val):
                    real_q4 = annual_val - q123_sum
                    fixed_df.at[row, q4_col] = real_q4
                    n_fixes += 1
                    if verbose and row in ("Total Revenue", "Net Income", "Operating Income",
                                            "Diluted EPS", "Basic EPS"):
                        print(f"    [Q4 fill from annual] {row} {year}: NaN → "
                              f"{real_q4:.2f} (annual {annual_val:.2f} - sum {q123_sum:.2f})")
                    continue

                # 케이스 2: Q4가 있는데 연간 누적값과 비슷함 (≈ 잘못 매칭됨)
                # → 진짜 Q4 = annual - Q1Q2Q3 으로 변환
                q4_val = float(q4_val)
                if annual_val != 0 and abs(q4_val - annual_val) / abs(annual_val) < 0.05:
                    real_q4 = annual_val - q123_sum
                    fixed_df.at[row, q4_col] = real_q4
                    n_fixes += 1
                    if verbose and row in ("Total Revenue", "Net Income", "Operating Income",
                                            "Diluted EPS", "Basic EPS"):
                        unit_label = "조" if abs(annual_val) > 1e9 else ""
                        scale = 1e12 if abs(annual_val) > 1e9 else 1
                        print(f"    [Q4 fix cumulative] {row} {year}: "
                              f"{q4_val/scale:.2f}{unit_label} → {real_q4/scale:.2f}{unit_label} "
                              f"(annual {annual_val/scale:.2f} - sum {q123_sum/scale:.2f})")
            except (KeyError, ValueError, TypeError):
                continue

        years_processed.add(year)

    if verbose and n_fixes > 0:
        print(f"  [Q4 cumulative fix] {n_fixes} cells corrected across {len(years_processed)} years")

    return fixed_df


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
    naver_data = None

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

        # 네이버 컨센서스 (한국 종목 미래 추정치 보강)
        # ⚠️ 실패해도 앱 안 죽음 (graceful degradation)
        try:
            from modules.data_sources.naver_source import fetch_naver_consensus
            ticker_6digit = ticker.replace(".KS", "").replace(".KQ", "")
            naver_data = fetch_naver_consensus(ticker_6digit)
            if naver_data is not None:
                sources_used.append("naver")
                if verbose:
                    print(f"  [naver] consensus fetched: "
                          f"{len(naver_data.get('quarterly', pd.DataFrame()).columns)}q, "
                          f"{len(naver_data.get('annual', pd.DataFrame()).columns)}y")
            elif verbose:
                print(f"  [naver] no consensus data")
        except Exception as e:
            naver_data = None
            if verbose:
                print(f"  [naver error, gracefully skipped] {e}")

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
    # 5-B. 한국 종목: Q4 누적값 보정 (DART 사업보고서 이슈)
    # ============================================================
    # DART 사업보고서(11011)는 연간 누적값을 보고하는데, 우리 병합 로직이
    # 분기말 날짜와 연간 마지막 날짜를 ±15일 이내로 매칭하면서
    # 연간 누적값이 Q4 자리로 들어옴 (예: 삼성전자 4Q25 매출 333조 = 연간 누적)
    # → flow 항목(매출, 영업이익, 순이익 등)에 대해 Q4 = 연간 - (Q1+Q2+Q3) 으로 변환
    if country == "KR" and dart_data:
        income_quarterly = _fix_q4_cumulative_to_quarterly(
            income_quarterly, income_annual, verbose=verbose
        )
        cashflow_quarterly = _fix_q4_cumulative_to_quarterly(
            cashflow_quarterly, cashflow_annual, verbose=verbose
        )
        # balance는 stock 항목이라 보정 불필요 (분기말 시점값)

    # ============================================================
    # 6. 메타 정보
    # ============================================================
    yf_sector = info.get("sector")
    yf_industry = info.get("industry")
    sector_internal = classify_sector(ticker, yf_sector, yf_industry)
    name = info.get("longName") or info.get("shortName") or ticker

    # 시총 계산: 보통주 기준 (가격 × 발행주식수)
    # yfinance의 marketCap은 한국 종목에서 우선주 포함 등으로 부정확할 때가 있음
    # (예: 삼성전자 yfinance marketCap = 2,291조 / 실제 보통주 시총 = 2,011조)
    # → 직접 계산 가능하면 그 값을 사용. 미국 종목은 두 값이 거의 일치.
    yf_market_cap = info.get("marketCap")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    shares = info.get("sharesOutstanding")

    if current_price and shares:
        calculated_market_cap = float(current_price) * float(shares)
        market_cap = calculated_market_cap
        market_cap_source = "calculated (price × shares)"
    elif yf_market_cap:
        market_cap = float(yf_market_cap)
        market_cap_source = "yfinance.marketCap (fallback)"
    else:
        market_cap = None
        market_cap_source = "unavailable"

    meta = {
        "ticker": ticker,
        "name": name,
        "country": country,
        "currency": currency,
        "sector_yf": yf_sector,
        "industry_yf": yf_industry,
        "sector_internal": sector_internal,
        "market_cap": market_cap,
        "market_cap_source": market_cap_source,
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
        "earnings_history":   yf_data.get("earnings_history", pd.DataFrame()),  # 분기 EPS 확장
        "dividends":          yf_data.get("dividends", pd.Series(dtype=float)),
        "shares_outstanding": info.get("sharesOutstanding"),
        "recommendations":    yf_data.get("recommendations"),

        # 한국 전용
        "kr_filings":         dart_data.get("recent_filings", pd.DataFrame()),
        "kr_investor_flow":   pykrx_data.get("investor_flow", pd.DataFrame()),
        "kr_short_selling":   pykrx_data.get("short_selling", pd.DataFrame()),
        "kr_foreign_holding": pykrx_data.get("foreign_holding", pd.DataFrame()),
        "kr_naver_consensus": naver_data,  # 네이버 컨센서스 (None 가능)

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
