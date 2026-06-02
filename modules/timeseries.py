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

    # 1. 분기 시계열 (과거 + 미래)
    quarterly = _build_quarterly_timeseries(
        income_q=income_q,
        n_history=n_quarters_history,
        user_quarterly_eps=user_quarterly_eps,
        naver_data=naver_data,
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
) -> pd.DataFrame:
    """분기 시계열 (과거 n개 + 미래 2개)."""
    rows = []

    # 1) 과거 분기 데이터 (yfinance + DART, 이미 data_loader에서 병합됨)
    revenue_series = get_row_series(income_q, INCOME_ROW_ALIASES["revenue"]).dropna()
    eps_series = get_row_series(income_q, INCOME_ROW_ALIASES["diluted_eps"]).dropna()
    if eps_series.empty:
        eps_series = get_row_series(income_q, INCOME_ROW_ALIASES["basic_eps"]).dropna()

    # 컬럼(분기) 정렬 (최신 → 과거)
    all_cols = sorted(set(revenue_series.index) | set(eps_series.index), reverse=True)
    history_cols = all_cols[:n_history]
    # 표시는 과거 → 최신 순으로
    history_cols = sorted(history_cols)

    # YoY 계산을 위해 1년 전 데이터도 필요
    for col in history_cols:
        period_label = _format_quarter_label(col)
        revenue = _safe_get(revenue_series, col)
        eps = _safe_get(eps_series, col)

        # YoY: 1년 전 (4분기 전) 찾기
        revenue_yoy = _calc_yoy_quarterly(revenue_series, col)
        eps_yoy = _calc_yoy_quarterly(eps_series, col)

        rows.append({
            "period": period_label,
            "revenue": revenue,
            "revenue_yoy": revenue_yoy,
            "eps": eps,
            "eps_yoy": eps_yoy,
            "roe": None,  # 분기 ROE는 노이즈 큼, 생략
            "is_future": False,
            "source": "actual",
        })

    # 2) 미래 분기 (네이버 + 사용자 입력)
    future_rows = _build_future_quarterly_rows(
        last_actual_col=history_cols[-1] if history_cols else None,
        last_actual_revenue=rows[-1]["revenue"] if rows else None,
        last_actual_eps=rows[-1]["eps"] if rows else None,
        user_quarterly_eps=user_quarterly_eps,
        naver_data=naver_data,
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
    eps_series = get_row_series(income_a, INCOME_ROW_ALIASES["diluted_eps"]).dropna()
    if eps_series.empty:
        eps_series = get_row_series(income_a, INCOME_ROW_ALIASES["basic_eps"]).dropna()
    net_income_series = get_row_series(income_a, INCOME_ROW_ALIASES["net_income"]).dropna()
    equity_series = get_row_series(balance_a, BALANCE_ROW_ALIASES["stockholders_equity"]).dropna()

    all_cols = sorted(set(revenue_series.index) | set(eps_series.index), reverse=True)
    history_cols = all_cols[:n_history]
    history_cols = sorted(history_cols)

    for col in history_cols:
        period_label = _format_year_label(col)
        revenue = _safe_get(revenue_series, col)
        eps = _safe_get(eps_series, col)
        net_income = _safe_get(net_income_series, col)
        equity = _safe_get(equity_series, col)

        revenue_yoy = _calc_yoy_annual(revenue_series, col)
        eps_yoy = _calc_yoy_annual(eps_series, col)
        roe = safe_divide(net_income, equity)

        rows.append({
            "period": period_label,
            "revenue": revenue,
            "revenue_yoy": revenue_yoy,
            "eps": eps,
            "eps_yoy": eps_yoy,
            "roe": roe,
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
        period_label = f"{year}.12"
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

        future_rows.append({
            "period": period_label,
            "revenue": revenue,
            "revenue_yoy": revenue_yoy,
            "eps": eps,
            "eps_yoy": eps_yoy,
            "roe": None,  # 미래 ROE는 자기자본 추정 어려움
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
    """Timestamp 또는 str을 'YYYY.MM' 형식으로."""
    try:
        ts = pd.Timestamp(col)
        return f"{ts.year}.{ts.month:02d}"
    except (TypeError, ValueError):
        return str(col)


def _format_year_label(col) -> str:
    """Timestamp 또는 str을 'YYYY.12' 형식으로."""
    try:
        ts = pd.Timestamp(col)
        return f"{ts.year}.{ts.month:02d}"
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
    """마지막 분기 다음 n개 분기 라벨 만들기."""
    try:
        ts = pd.Timestamp(last_col)
    except (TypeError, ValueError):
        return []

    labels = []
    for i in range(1, n + 1):
        next_ts = ts + pd.DateOffset(months=3 * i)
        labels.append(f"{next_ts.year}.{next_ts.month:02d}")
    return labels


def _calc_yoy_for_future_eps(period_label: str, eps: float,
                              history_eps_series: pd.Series) -> Optional[float]:
    """미래 분기 EPS의 YoY (1년 전 실제 분기와 비교)."""
    try:
        year, month = period_label.split(".")
        target_ts = pd.Timestamp(f"{int(year) - 1}-{int(month):02d}-01") + pd.offsets.MonthEnd(0)
    except (ValueError, TypeError):
        return None

    tolerance = pd.Timedelta(days=45)
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
# Naver 데이터에서 특정 기간 값 추출 (단순화: 일단 None 반환)
# ============================================================
def _get_naver_quarterly_eps(naver_data: dict, period_label: str) -> Optional[float]:
    """네이버 데이터에서 특정 분기의 EPS 추출. 현재는 단순 매칭."""
    if naver_data is None:
        return None
    df = naver_data.get("quarterly", pd.DataFrame())
    if df.empty:
        return None

    # 행 이름이 'EPS(원)' 또는 'EPS' 같은 패턴
    for idx in df.index:
        if "EPS" in str(idx):
            # 컬럼명에서 매칭 (period_label과 동일하거나 '(E)' 포함)
            for col in df.columns:
                col_str = str(col).replace("(E)", "").replace("(P)", "").strip()
                if col_str == period_label:
                    val = df.at[idx, col]
                    if pd.notna(val):
                        return float(val)
    return None


def _get_naver_quarterly_revenue(naver_data: dict, period_label: str) -> Optional[float]:
    if naver_data is None:
        return None
    df = naver_data.get("quarterly", pd.DataFrame())
    if df.empty:
        return None
    for idx in df.index:
        if "매출" in str(idx):
            for col in df.columns:
                col_str = str(col).replace("(E)", "").replace("(P)", "").strip()
                if col_str == period_label:
                    val = df.at[idx, col]
                    if pd.notna(val):
                        return float(val) * 100_000_000  # 억원 → 원
    return None


def _get_naver_annual_eps(naver_data: dict, period_label: str) -> Optional[float]:
    if naver_data is None:
        return None
    df = naver_data.get("annual", pd.DataFrame())
    if df.empty:
        return None
    for idx in df.index:
        if "EPS" in str(idx):
            for col in df.columns:
                col_str = str(col).replace("(E)", "").replace("(P)", "").strip()
                if col_str == period_label:
                    val = df.at[idx, col]
                    if pd.notna(val):
                        return float(val)
    return None


def _get_naver_annual_revenue(naver_data: dict, period_label: str) -> Optional[float]:
    if naver_data is None:
        return None
    df = naver_data.get("annual", pd.DataFrame())
    if df.empty:
        return None
    for idx in df.index:
        if "매출" in str(idx):
            for col in df.columns:
                col_str = str(col).replace("(E)", "").replace("(P)", "").strip()
                if col_str == period_label:
                    val = df.at[idx, col]
                    if pd.notna(val):
                        return float(val) * 100_000_000
    return None
