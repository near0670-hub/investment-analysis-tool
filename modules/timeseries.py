"""
modules/timeseries.py — 분기/연간 시계열 추출

목적: 본인이 원하는 화면 (분기 5~6개 + 연간 5~6년, 미래 구간 강조) 을 위한
시계열 DataFrame 만들기.

데이터 소스 우선순위:
- 과거: yfinance + DART (이미 data_loader가 처리)
- 미래: (1) 사용자 수동 입력 → (2) 네이버 크롤링 → (3) yfinance.forwardEps

출력 스키마:
{
    "quarterly": pd.DataFrame,
    "annual": pd.DataFrame,
    "quarterly_future_periods": [str, ...],
    "annual_future_periods": [str, ...],
}

DataFrame 컬럼:
    period (str) — 표시 라벨 ("2025.06", "2026.12")
    revenue (float, 보고 통화)
    revenue_yoy (float, 0-1 scale)
    eps (float)
    eps_yoy (float)
    roe (float, 연간만; 분기는 None)
    is_future (bool) — 컨센서스/추정치 여부
    source (str) — "actual" or "consensus" or "user_input"
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from modules.financial_metrics import (
    INCOME_ROW_ALIASES, BALANCE_ROW_ALIASES,
    get_row_series,
)
from utils.validation import safe_growth, safe_divide


# ============================================================
# 메인 함수
# ============================================================
def extract_timeseries(
    data: dict,
    n_quarters_history: int = 4,
    n_years_history: int = 4,
    user_quarterly_eps: Optional[list[float]] = None,
    user_annual_eps: Optional[list[float]] = None,
    naver_data: Optional[dict] = None,
) -> dict:
    """
    분기/연간 시계열 추출.

    Args:
        data: data_loader.load_company_data() 결과
        n_quarters_history: 과거 분기 개수 (보통 4)
        n_years_history: 과거 연도 개수 (보통 4)
        user_quarterly_eps: 사용자 입력 분기 미래 EPS (예: [Q+1, Q+2])
        user_annual_eps: 사용자 입력 연간 미래 EPS (예: [FY+1, FY+2])
        naver_data: naver_source.fetch_naver_consensus() 결과 (한국 종목용)

    Returns:
        {
            "quarterly": DataFrame,
            "annual": DataFrame,
            "quarterly_future_periods": [...],
            "annual_future_periods": [...],
        }
    """
    income_q = data.get("income_quarterly", pd.DataFrame())
    income_a = data.get("income_annual", pd.DataFrame())
    balance_a = data.get("balance_annual", pd.DataFrame())
    info = data.get("info", {})
    earnings_history = data.get("earnings_history", pd.DataFrame())

    # 1. 분기 시계열 (과거 + 미래)
    quarterly = _build_quarterly_timeseries(
        income_q=income_q,
        n_history=n_quarters_history,
        user_quarterly_eps=user_quarterly_eps,
        naver_data=naver_data,
        earnings_history=earnings_history,
    )

    # 2. 연간 시계열 (과거 + 미래)
    annual = _build_annual_timeseries(
        income_a=income_a,
        balance_a=balance_a,
        info=info,
        n_history=n_years_history,
        user_annual_eps=user_annual_eps,
        naver_data=naver_data,
    )

    return {
        "quarterly": quarterly,
        "annual": annual,
        "quarterly_future_periods": list(
            quarterly[quarterly["is_future"]]["period"].values
        ) if not quarterly.empty else [],
        "annual_future_periods": list(
            annual[annual["is_future"]]["period"].values
        ) if not annual.empty else [],
    }


# ============================================================
# 분기 시계열
# ============================================================
def _build_quarterly_timeseries(
    income_q: pd.DataFrame,
    n_history: int,
    user_quarterly_eps: Optional[list[float]],
    naver_data: Optional[dict],
    earnings_history: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """분기 시계열 (과거 n개 + 미래 2개).

    EPS 시리즈는 quarterly_financials (5분기) + earnings_history (8분기)를 병합해서
    더 긴 시계열로 만든다. Diluted EPS 우선, Basic EPS는 보조로 같이 들고감.
    """
    rows = []

    # 1) 과거 분기 데이터
    revenue_series = get_row_series(income_q, INCOME_ROW_ALIASES["revenue"]).dropna()
    diluted_eps_series = get_row_series(income_q, INCOME_ROW_ALIASES["diluted_eps"]).dropna()
    basic_eps_series = get_row_series(income_q, INCOME_ROW_ALIASES["basic_eps"]).dropna()

    # 메인 EPS 시리즈: Diluted 우선, 없으면 Basic
    eps_series = diluted_eps_series if not diluted_eps_series.empty else basic_eps_series

    # earnings_history로 EPS 시리즈 확장
    eps_series = _augment_eps_with_earnings_history(eps_series, earnings_history)

    # 매출 기반으로 history_cols 결정
    history_cols = sorted(revenue_series.index, reverse=True)[:n_history]
    history_cols = sorted(history_cols)

    for col in history_cols:
        period_label = _format_quarter_label(col)
        revenue = _safe_get(revenue_series, col)
        eps = _safe_get(eps_series, col)
        eps_basic = _safe_get(basic_eps_series, col)  # 보조

        revenue_yoy = _calc_yoy_quarterly(revenue_series, col)
        eps_yoy = _calc_yoy_quarterly(eps_series, col)

        rows.append({
            "period": period_label,
            "revenue": revenue,
            "revenue_yoy": revenue_yoy,
            "eps": eps,
            "eps_basic": eps_basic,
            "eps_yoy": eps_yoy,
            "roe": None,
            "is_future": False,
            "source": "actual",
        })

    # 2) 미래 분기
    future_rows = _build_future_quarterly_rows(
        last_actual_col=history_cols[-1] if history_cols else None,
        last_actual_revenue=rows[-1]["revenue"] if rows else None,
        last_actual_eps=rows[-1]["eps"] if rows else None,
        user_quarterly_eps=user_quarterly_eps,
        naver_data=naver_data,
        history_revenue_series=revenue_series,
        history_eps_series=eps_series,
    )
    # 미래 행에는 eps_basic이 없음 → None으로 채움
    for fr in future_rows:
        if "eps_basic" not in fr:
            fr["eps_basic"] = None
    rows.extend(future_rows)

    if not rows:
        return pd.DataFrame(columns=[
            "period", "revenue", "revenue_yoy", "eps", "eps_basic", "eps_yoy",
            "roe", "is_future", "source"
        ])

    return pd.DataFrame(rows)


def _augment_eps_with_earnings_history(
    eps_series: pd.Series,
    earnings_history: Optional[pd.DataFrame],
) -> pd.Series:
    """
    yfinance earnings_history (분기 EPS 8개)를 quarterly_financials EPS와 병합.

    earnings_history는 보통 'epsActual', 'epsEstimate' 같은 컬럼을 가짐.
    실제 EPS인 'epsActual'을 사용. 기존 eps_series에 없는 분기만 추가.
    """
    if earnings_history is None or earnings_history.empty:
        return eps_series

    # 'epsActual' 컬럼 찾기
    eps_col = None
    for candidate in ["epsActual", "actualEps", "EPS Actual", "epsactual"]:
        if candidate in earnings_history.columns:
            eps_col = candidate
            break
    if eps_col is None:
        return eps_series

    augmented = eps_series.copy()

    for idx in earnings_history.index:
        try:
            ts = pd.Timestamp(idx)
            val = earnings_history.at[idx, eps_col]
            if pd.isna(val):
                continue

            # 기존 시리즈에 이미 비슷한 날짜(±45일)가 있으면 skip
            already_exists = False
            for existing in augmented.index:
                try:
                    if abs(pd.Timestamp(existing) - ts) <= pd.Timedelta(days=45):
                        already_exists = True
                        break
                except (TypeError, ValueError):
                    continue
            if not already_exists:
                augmented[ts] = float(val)
        except (TypeError, ValueError, KeyError):
            continue

    # 정렬해서 반환
    augmented = augmented.dropna().sort_index(ascending=False)
    return augmented


def _build_future_quarterly_rows(
    last_actual_col,
    last_actual_revenue,
    last_actual_eps,
    user_quarterly_eps: Optional[list[float]],
    naver_data: Optional[dict],
    history_revenue_series: pd.Series,
    history_eps_series: pd.Series,
) -> list[dict]:
    """미래 분기 행 생성. 사용자 입력 우선, 없으면 네이버."""
    future_rows = []

    # 미래 분기 라벨 만들기 (마지막 실제 + 1, 2분기 후)
    if last_actual_col is None:
        return []

    next_periods = _next_quarter_labels(last_actual_col, n=2)

    for i, period_label in enumerate(next_periods):
        eps = None
        source = None

        # 1순위: 사용자 입력
        if user_quarterly_eps and i < len(user_quarterly_eps) and user_quarterly_eps[i] is not None:
            eps = user_quarterly_eps[i]
            source = "user_input"
        # 2순위: 네이버 컨센서스 (분기)
        elif naver_data is not None:
            eps = _get_naver_quarterly_eps(naver_data, period_label)
            if eps is not None:
                source = "consensus"

        if eps is None:
            continue  # 데이터 없으면 미래 행 자체를 만들지 않음

        # YoY 계산 (1년 전 실제 분기와 비교)
        eps_yoy = _calc_yoy_for_future_eps(period_label, eps, history_eps_series)

        # 매출은 네이버에서 가져오기 시도, 없으면 None
        revenue = None
        revenue_yoy = None
        if naver_data is not None:
            revenue = _get_naver_quarterly_revenue(naver_data, period_label)
            if revenue is not None:
                revenue_yoy = _calc_yoy_for_future_revenue(period_label, revenue, history_revenue_series)

        future_rows.append({
            "period": period_label,
            "revenue": revenue,
            "revenue_yoy": revenue_yoy,
            "eps": eps,
            "eps_yoy": eps_yoy,
            "roe": None,
            "is_future": True,
            "source": source,
        })

    return future_rows


# ============================================================
# 연간 시계열
# ============================================================
def _build_annual_timeseries(
    income_a: pd.DataFrame,
    balance_a: pd.DataFrame,
    info: dict,
    n_history: int,
    user_annual_eps: Optional[list[float]],
    naver_data: Optional[dict],
) -> pd.DataFrame:
    """연간 시계열 (과거 n개 + 미래 2개)."""
    rows = []

    revenue_series = get_row_series(income_a, INCOME_ROW_ALIASES["revenue"]).dropna()
    diluted_eps_series = get_row_series(income_a, INCOME_ROW_ALIASES["diluted_eps"]).dropna()
    basic_eps_series = get_row_series(income_a, INCOME_ROW_ALIASES["basic_eps"]).dropna()
    eps_series = diluted_eps_series if not diluted_eps_series.empty else basic_eps_series
    net_income_series = get_row_series(income_a, INCOME_ROW_ALIASES["net_income"]).dropna()
    equity_series = get_row_series(balance_a, BALANCE_ROW_ALIASES["stockholders_equity"]).dropna()

    all_cols = sorted(set(revenue_series.index) | set(eps_series.index), reverse=True)
    history_cols = all_cols[:n_history]
    history_cols = sorted(history_cols)

    for col in history_cols:
        period_label = _format_year_label(col)
        revenue = _safe_get(revenue_series, col)
        eps = _safe_get(eps_series, col)
        eps_basic = _safe_get(basic_eps_series, col)
        net_income = _safe_get(net_income_series, col)
        equity = _safe_get(equity_series, col)

        revenue_yoy = _calc_yoy_annual(revenue_series, col)
        eps_yoy = _calc_yoy_annual(eps_series, col)
        roe = safe_divide(net_income, equity)
        roe_source = "computed" if roe is not None else None

        # ROE가 None이면 네이버 ROE로 fallback (한국 종목)
        if roe is None and naver_data is not None:
            naver_roe = _get_naver_annual_roe(naver_data, period_label)
            if naver_roe is not None:
                roe = naver_roe / 100.0  # 네이버는 % 단위 → 비율로
                roe_source = "naver"

        rows.append({
            "period": period_label,
            "revenue": revenue,
            "revenue_yoy": revenue_yoy,
            "eps": eps,
            "eps_basic": eps_basic,
            "eps_yoy": eps_yoy,
            "roe": roe,
            "roe_source": roe_source,
            "is_future": False,
            "source": "actual",
        })

    # 미래 연도
    future_rows = _build_future_annual_rows(
        last_actual_col=history_cols[-1] if history_cols else None,
        user_annual_eps=user_annual_eps,
        naver_data=naver_data,
        info=info,
        history_revenue_series=revenue_series,
        history_eps_series=eps_series,
    )
    rows.extend(future_rows)

    if not rows:
        return pd.DataFrame(columns=[
            "period", "revenue", "revenue_yoy", "eps", "eps_yoy",
            "roe", "is_future", "source"
        ])

    return pd.DataFrame(rows)


def _build_future_annual_rows(
    last_actual_col,
    user_annual_eps: Optional[list[float]],
    naver_data: Optional[dict],
    info: dict,
    history_revenue_series: pd.Series,
    history_eps_series: pd.Series,
) -> list[dict]:
    """미래 연도 행 생성."""
    future_rows = []

    if last_actual_col is None:
        return []

    last_year = pd.Timestamp(last_actual_col).year
    next_years = [last_year + 1, last_year + 2]

    for i, year in enumerate(next_years):
        period_label = f"FY{year % 100:02d}"
        eps = None
        source = None

        # 1순위: 사용자 입력
        if user_annual_eps and i < len(user_annual_eps) and user_annual_eps[i] is not None:
            eps = user_annual_eps[i]
            source = "user_input"
        # 2순위: 네이버
        elif naver_data is not None:
            eps = _get_naver_annual_eps(naver_data, period_label)
            if eps is not None:
                source = "consensus"
        # 3순위: yfinance forwardEps (1년만)
        elif i == 0 and info.get("forwardEps") is not None:
            eps = info.get("forwardEps")
            source = "consensus"

        if eps is None:
            continue

        eps_yoy = _calc_yoy_for_future_eps_annual(year, eps, history_eps_series)

        revenue = None
        revenue_yoy = None
        if naver_data is not None:
            revenue = _get_naver_annual_revenue(naver_data, period_label)
            if revenue is not None:
                revenue_yoy = _calc_yoy_for_future_revenue_annual(year, revenue, history_revenue_series)

        # 미래 ROE: 네이버 컨센서스에서 가져오기 (한국 종목)
        future_roe = None
        roe_source = None
        if naver_data is not None:
            naver_roe = _get_naver_annual_roe(naver_data, period_label)
            if naver_roe is not None:
                future_roe = naver_roe / 100.0
                roe_source = "naver"

        future_rows.append({
            "period": period_label,
            "revenue": revenue,
            "revenue_yoy": revenue_yoy,
            "eps": eps,
            "eps_basic": None,
            "eps_yoy": eps_yoy,
            "roe": future_roe,
            "roe_source": roe_source,
            "is_future": True,
            "source": source,
        })

    return future_rows


# ============================================================
# Helpers
# ============================================================
def _safe_get(series: pd.Series, key) -> Optional[float]:
    if key not in series.index:
        return None
    val = series[key]
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _format_quarter_label(col) -> str:
    """
    Timestamp을 '3Q25' 형식으로 (분기 먼저, 연도 뒤 - 블룸버그/IB 표준).
    예: 2025-07-31 → 3Q25, 2026-01-31 → 1Q26
    """
    try:
        ts = pd.Timestamp(col)
        year_short = ts.year % 100  # 2025 → 25
        month = ts.month
        # 분기 매핑: 1-3=Q1, 4-6=Q2, 7-9=Q3, 10-12=Q4
        quarter = (month - 1) // 3 + 1
        return f"{quarter}Q{year_short:02d}"
    except (TypeError, ValueError):
        return str(col)


def _format_year_label(col) -> str:
    """Timestamp을 'FY25' 형식으로 (회계연도)."""
    try:
        ts = pd.Timestamp(col)
        year_short = ts.year % 100
        return f"FY{year_short:02d}"
    except (TypeError, ValueError):
        return str(col)


def _calc_yoy_quarterly(series: pd.Series, current_col) -> Optional[float]:
    """분기 YoY: 1년 전(약 365일 전) 분기와 비교."""
    if current_col not in series.index:
        return None
    try:
        current_ts = pd.Timestamp(current_col)
    except (TypeError, ValueError):
        return None

    target_ts = current_ts - pd.DateOffset(years=1)
    tolerance = pd.Timedelta(days=45)

    closest = None
    closest_diff = tolerance
    for c in series.index:
        try:
            c_ts = pd.Timestamp(c)
        except (TypeError, ValueError):
            continue
        diff = abs(c_ts - target_ts)
        if diff <= closest_diff:
            closest = c
            closest_diff = diff

    if closest is None:
        return None

    prev = _safe_get(series, closest)
    curr = _safe_get(series, current_col)
    return safe_growth(curr, prev)


def _calc_yoy_annual(series: pd.Series, current_col) -> Optional[float]:
    """연간 YoY: 1년 전(이전 연도) 값과 비교."""
    if current_col not in series.index:
        return None
    try:
        current_ts = pd.Timestamp(current_col)
    except (TypeError, ValueError):
        return None

    target_year = current_ts.year - 1
    for c in series.index:
        try:
            c_ts = pd.Timestamp(c)
            if c_ts.year == target_year:
                prev = _safe_get(series, c)
                curr = _safe_get(series, current_col)
                return safe_growth(curr, prev)
        except (TypeError, ValueError):
            continue
    return None


def _next_quarter_labels(last_col, n: int = 2) -> list[str]:
    """마지막 분기 다음 n개 분기 라벨 만들기 (25Q1 형식)."""
    try:
        ts = pd.Timestamp(last_col)
    except (TypeError, ValueError):
        return []

    labels = []
    for i in range(1, n + 1):
        next_ts = ts + pd.DateOffset(months=3 * i)
        year_short = next_ts.year % 100
        quarter = (next_ts.month - 1) // 3 + 1
        labels.append(f"{quarter}Q{year_short:02d}")
    return labels


def _calc_yoy_for_future_eps(period_label: str, eps: float,
                              history_eps_series: pd.Series) -> Optional[float]:
    """미래 분기 EPS의 YoY (1년 전 실제 분기와 비교)."""
    # 라벨 파싱: '1Q25' → quarter=1, year=2025
    import re as _re
    m = _re.match(r"^(\d)Q(\d{2})$", period_label)
    if not m:
        return None
    quarter = int(m.group(1))
    year = 2000 + int(m.group(2))
    # 분기 → 마지막 월 (3, 6, 9, 12)
    target_month = quarter * 3
    try:
        target_ts = pd.Timestamp(f"{year - 1}-{target_month:02d}-15")
    except (ValueError, TypeError):
        return None

    tolerance = pd.Timedelta(days=60)
    closest = None
    closest_diff = tolerance
    for c in history_eps_series.index:
        try:
            c_ts = pd.Timestamp(c)
        except (TypeError, ValueError):
            continue
        diff = abs(c_ts - target_ts)
        if diff <= closest_diff:
            closest = c
            closest_diff = diff

    if closest is None:
        return None

    prev = _safe_get(history_eps_series, closest)
    return safe_growth(eps, prev)


def _calc_yoy_for_future_revenue(period_label: str, revenue: float,
                                  history_revenue_series: pd.Series) -> Optional[float]:
    """미래 분기 매출의 YoY."""
    return _calc_yoy_for_future_eps(period_label, revenue, history_revenue_series)


def _calc_yoy_for_future_eps_annual(year: int, eps: float,
                                     history_eps_series: pd.Series) -> Optional[float]:
    """미래 연도 EPS의 YoY."""
    prev_year = year - 1
    for c in history_eps_series.index:
        try:
            if pd.Timestamp(c).year == prev_year:
                prev = _safe_get(history_eps_series, c)
                return safe_growth(eps, prev)
        except (TypeError, ValueError):
            continue
    return None


def _calc_yoy_for_future_revenue_annual(year: int, revenue: float,
                                         history_revenue_series: pd.Series) -> Optional[float]:
    return _calc_yoy_for_future_eps_annual(year, revenue, history_revenue_series)


# ============================================================
# Naver 데이터에서 특정 기간 값 추출
# 새 네이버 파서 (v2)의 표준 형식: 행=영문 표준명, 열=Timestamp
# ============================================================
def _label_to_naver_ts(period_label: str, is_quarterly: bool = True) -> Optional[pd.Timestamp]:
    """
    우리 라벨('3Q25', 'FY25') → 네이버 Timestamp 형식 변환.
    """
    import re as _re
    if is_quarterly:
        m = _re.match(r"^(\d)Q(\d{2})$", period_label)
        if not m:
            return None
        quarter = int(m.group(1))
        year = 2000 + int(m.group(2))
        month = quarter * 3
        last_day = 31 if month in (3, 12) else 30
        try:
            return pd.Timestamp(f"{year}-{month:02d}-{last_day:02d}")
        except (ValueError, TypeError):
            return None
    else:
        # 연간: 'FY25' → 2025-12-31
        m = _re.match(r"^FY(\d{2})$", period_label)
        if not m:
            return None
        year = 2000 + int(m.group(1))
        try:
            return pd.Timestamp(f"{year}-12-31")
        except (ValueError, TypeError):
            return None


def _naver_lookup(df: pd.DataFrame, row_name: str, target_ts: pd.Timestamp,
                  tolerance_days: int = 45) -> Optional[float]:
    """네이버 DataFrame에서 row × 가장 가까운 컬럼 찾기."""
    if df is None or df.empty:
        return None
    if row_name not in df.index:
        return None

    tolerance = pd.Timedelta(days=tolerance_days)
    best_col = None
    best_diff = tolerance
    for col in df.columns:
        try:
            col_ts = pd.Timestamp(col)
        except (TypeError, ValueError):
            continue
        diff = abs(col_ts - target_ts)
        if diff <= best_diff:
            best_col = col
            best_diff = diff

    if best_col is None:
        return None

    val = df.at[row_name, best_col]
    if pd.isna(val):
        return None
    return float(val)


def _get_naver_quarterly_eps(naver_data: dict, period_label: str) -> Optional[float]:
    """네이버에서 특정 분기 EPS 추출 (예: '3Q25' → 71,049 원)."""
    if naver_data is None:
        return None
    target_ts = _label_to_naver_ts(period_label, is_quarterly=True)
    if target_ts is None:
        return None
    return _naver_lookup(naver_data.get("quarterly", pd.DataFrame()),
                         "EPS Naver", target_ts)


def _get_naver_quarterly_revenue(naver_data: dict, period_label: str) -> Optional[float]:
    """네이버에서 특정 분기 매출 추출 (이미 원 단위로 변환됨)."""
    if naver_data is None:
        return None
    target_ts = _label_to_naver_ts(period_label, is_quarterly=True)
    if target_ts is None:
        return None
    return _naver_lookup(naver_data.get("quarterly", pd.DataFrame()),
                         "Total Revenue", target_ts)


def _get_naver_annual_eps(naver_data: dict, period_label: str) -> Optional[float]:
    """네이버에서 특정 연도 EPS 추출 (예: 'FY26' → 138,478 원)."""
    if naver_data is None:
        return None
    target_ts = _label_to_naver_ts(period_label, is_quarterly=False)
    if target_ts is None:
        return None
    return _naver_lookup(naver_data.get("annual", pd.DataFrame()),
                         "EPS Naver", target_ts)


def _get_naver_annual_revenue(naver_data: dict, period_label: str) -> Optional[float]:
    if naver_data is None:
        return None
    target_ts = _label_to_naver_ts(period_label, is_quarterly=False)
    if target_ts is None:
        return None
    return _naver_lookup(naver_data.get("annual", pd.DataFrame()),
                         "Total Revenue", target_ts)


def _get_naver_annual_roe(naver_data: dict, period_label: str) -> Optional[float]:
    """네이버에서 특정 연도 ROE(지배주주) 추출. 단위는 % (그대로 반환, 호출자가 /100)."""
    if naver_data is None:
        return None
    target_ts = _label_to_naver_ts(period_label, is_quarterly=False)
    if target_ts is None:
        return None
    return _naver_lookup(naver_data.get("annual", pd.DataFrame()),
                         "ROE", target_ts)
