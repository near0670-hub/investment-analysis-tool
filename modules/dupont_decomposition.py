"""
modules/dupont_decomposition.py — ROE 듀퐁 3단계 분해

ROE = 순이익률 × 자산회전율 × 레버리지
     (Net Margin) × (Asset Turnover) × (Equity Multiplier)

데이터 소스:
- 한국 종목: 네이버 (순이익률/ROE) + DART (자산/자본 평균 계산용)
- 미국 종목: yfinance (모든 항목)

평균 자산/자본 = (기초 + 기말) / 2 (네이버/CFA 표준)

출력 구조:
{
    "components": pd.DataFrame  # rows=항목, cols=기간
    "roe_change_components": dict  # 동인 분해 결과
    "narrative": str  # 자동 생성 한 줄 해설
    "source_note": str  # 회계 표준 + 출처 명시
    "country": str  # KR / US
}
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from modules.financial_metrics import (
    INCOME_ROW_ALIASES, BALANCE_ROW_ALIASES,
    get_row_series,
)
from utils.validation import safe_divide, safe_growth


# ============================================================
# 메인 함수
# ============================================================
def calculate_dupont(data: dict, n_history: int = 2) -> Optional[dict]:
    """
    ROE 듀퐁 3단계 분해 계산.

    Args:
        data: data_loader.load_company_data() 결과
        n_history: 과거 연도 개수 (기본 2년) → +1년 컨센서스 = 총 3개 기간

    Returns:
        성공 시 dict, 실패 시 None
    """
    country = data.get("meta", {}).get("country", "US")

    if country == "KR":
        return _calculate_dupont_kr(data, n_history)
    else:
        return _calculate_dupont_us(data, n_history)


# ============================================================
# 한국 종목: 네이버 + DART
# ============================================================
def _calculate_dupont_kr(data: dict, n_history: int) -> Optional[dict]:
    """한국 종목 듀퐁 분해. 네이버 우선, DART 보조."""
    naver_data = data.get("kr_naver_consensus")
    balance_annual = data.get("balance_annual", pd.DataFrame())
    income_annual = data.get("income_annual", pd.DataFrame())

    if naver_data is None:
        return None

    naver_annual = naver_data.get("annual", pd.DataFrame())
    if naver_annual.empty:
        return None

    # 네이버 연간 컬럼 (Timestamp) - 과거 n_history + 컨센서스 1
    naver_cols = sorted(naver_annual.columns)
    if len(naver_cols) < 2:
        return None

    # 최근 n_history + 1 (컨센서스) = n_history + 1 기간
    # 네이버는 보통 [과거3, 컨센서스1] = 4개
    # n_history=2 → 과거 2개 + 컨센서스 1개 = 3개
    selected_cols = naver_cols[-(n_history + 1):]

    # 자산/자본 평균 계산용 - DART balance에서
    avg_assets, avg_equity = _calculate_average_balance_kr(
        balance_annual, naver_data, selected_cols
    )

    # 컴포넌트 계산
    rows = []
    for col in selected_cols:
        period_label = _format_year(col)
        is_consensus = _is_consensus_period(naver_data, col)

        # 네이버에서 직접 가져오기
        net_margin_pct = _safe_at(naver_annual, "Net Margin", col)  # %
        roe_pct = _safe_at(naver_annual, "ROE", col)  # %
        revenue = _safe_at(naver_annual, "Total Revenue", col)  # 원
        net_income = _safe_at(naver_annual, "Net Income", col)  # 원

        # 자산회전율 = 매출 / 평균자산
        asset_turnover = None
        if revenue is not None and avg_assets.get(col) is not None:
            asset_turnover = safe_divide(revenue, avg_assets[col])

        # 레버리지 = 평균자산 / 평균자본
        leverage = None
        if avg_assets.get(col) is not None and avg_equity.get(col) is not None:
            leverage = safe_divide(avg_assets[col], avg_equity[col])

        # 순이익률 (네이버는 % 단위)
        net_margin = net_margin_pct / 100.0 if net_margin_pct is not None else None

        # ROE = 순이익률 × 자산회전율 × 레버리지 (검증용)
        roe_computed = None
        if all(v is not None for v in [net_margin, asset_turnover, leverage]):
            roe_computed = net_margin * asset_turnover * leverage

        # ROE 표시값은 네이버 직접 (있으면), 아니면 계산값
        roe_display = roe_pct / 100.0 if roe_pct is not None else roe_computed

        rows.append({
            "period": period_label,
            "is_consensus": is_consensus,
            "net_margin": net_margin,
            "asset_turnover": asset_turnover,
            "leverage": leverage,
            "roe_display": roe_display,
            "roe_computed": roe_computed,
            "revenue": revenue,
            "net_income": net_income,
            "avg_assets": avg_assets.get(col),
            "avg_equity": avg_equity.get(col),
        })

    if len(rows) < 2:
        return None

    components_df = pd.DataFrame(rows)

    # 동인 분해 + 해설
    roe_change = _decompose_roe_change(components_df)
    narrative = _generate_narrative(components_df, roe_change)

    return {
        "components": components_df,
        "roe_change_components": roe_change,
        "narrative": narrative,
        "source_note": "Source: Naver Securities + DART · K-IFRS 연결 · "
                       "Asset/Equity at period-average",
        "country": "KR",
    }


def _calculate_average_balance_kr(
    balance_annual: pd.DataFrame,
    naver_data: dict,
    selected_cols: list,
) -> tuple[dict, dict]:
    """
    각 연도의 평균 자산/자본 계산.

    평균 = (기초 + 기말) / 2 = (전년말 + 당년말) / 2

    DART balance_annual에서 가져옴. 컨센서스 연도는 마지막 actual 사용 (보수적).
    """
    avg_assets = {}
    avg_equity = {}

    total_assets = get_row_series(balance_annual, BALANCE_ROW_ALIASES["total_assets"]).dropna()
    total_equity = get_row_series(balance_annual, BALANCE_ROW_ALIASES["stockholders_equity"]).dropna()

    # 모든 balance 데이터를 year로 매핑
    asset_by_year = {pd.Timestamp(c).year: float(v) for c, v in total_assets.items()
                     if pd.notna(v)}
    equity_by_year = {pd.Timestamp(c).year: float(v) for c, v in total_equity.items()
                      if pd.notna(v)}

    for col in selected_cols:
        try:
            year = pd.Timestamp(col).year
        except (TypeError, ValueError):
            continue

        # 당년말 자산
        end_assets = asset_by_year.get(year)
        end_equity = equity_by_year.get(year)

        # 전년말 자산
        prev_assets = asset_by_year.get(year - 1)
        prev_equity = equity_by_year.get(year - 1)

        # 평균 계산 (둘 다 있으면 평균, 하나만 있으면 그것)
        if end_assets is not None and prev_assets is not None:
            avg_assets[col] = (end_assets + prev_assets) / 2
        elif end_assets is not None:
            avg_assets[col] = end_assets
        elif prev_assets is not None:
            avg_assets[col] = prev_assets

        if end_equity is not None and prev_equity is not None:
            avg_equity[col] = (end_equity + prev_equity) / 2
        elif end_equity is not None:
            avg_equity[col] = end_equity
        elif prev_equity is not None:
            avg_equity[col] = prev_equity

    # 컨센서스 연도: 자산/자본 추정 안 됨 → 마지막 actual 사용
    actual_cols = [c for c in selected_cols
                   if not _is_consensus_period(naver_data, c)]
    if actual_cols:
        last_actual = actual_cols[-1]
        last_actual_assets = avg_assets.get(last_actual)
        last_actual_equity = avg_equity.get(last_actual)

        for col in selected_cols:
            if _is_consensus_period(naver_data, col):
                if col not in avg_assets and last_actual_assets is not None:
                    avg_assets[col] = last_actual_assets
                if col not in avg_equity and last_actual_equity is not None:
                    avg_equity[col] = last_actual_equity

    return avg_assets, avg_equity


def _is_consensus_period(naver_data: dict, col) -> bool:
    """해당 컬럼이 컨센서스(E) 기간인지 확인."""
    if naver_data is None:
        return False
    future_periods = naver_data.get("future_periods", [])
    try:
        year = pd.Timestamp(col).year
        for fp in future_periods:
            # 예: '2026.12(E)' → year=2026
            import re
            m = re.match(r"^(\d{4})", fp)
            if m and int(m.group(1)) == year:
                return True
    except (TypeError, ValueError):
        pass
    return False


# ============================================================
# 미국 종목: yfinance
# ============================================================
def _calculate_dupont_us(data: dict, n_history: int) -> Optional[dict]:
    """미국 종목 듀퐁 분해. yfinance 데이터만 사용."""
    income_annual = data.get("income_annual", pd.DataFrame())
    balance_annual = data.get("balance_annual", pd.DataFrame())
    info = data.get("info", {})

    if income_annual.empty or balance_annual.empty:
        return None

    revenue_series = get_row_series(income_annual, INCOME_ROW_ALIASES["revenue"]).dropna()
    net_income_series = get_row_series(income_annual, INCOME_ROW_ALIASES["net_income"]).dropna()
    total_assets_series = get_row_series(balance_annual, BALANCE_ROW_ALIASES["total_assets"]).dropna()
    equity_series = get_row_series(balance_annual, BALANCE_ROW_ALIASES["stockholders_equity"]).dropna()

    # 공통 연도만 추출
    common_years = (set(revenue_series.index) & set(net_income_series.index)
                    & set(total_assets_series.index) & set(equity_series.index))
    sorted_cols = sorted(common_years)

    if len(sorted_cols) < n_history:
        return None

    # 과거 n_history개 actual
    actual_cols = sorted_cols[-n_history:]

    # 컨센서스 연도 (forwardEps 활용 시도)
    consensus_col = None
    forward_eps = info.get("forwardEps")
    last_actual_col = actual_cols[-1] if actual_cols else None

    rows = []
    asset_by_year = {pd.Timestamp(c).year: float(v) for c, v in total_assets_series.items()
                     if pd.notna(v)}
    equity_by_year = {pd.Timestamp(c).year: float(v) for c, v in equity_series.items()
                      if pd.notna(v)}

    for col in actual_cols:
        period_label = _format_year(col)
        year = pd.Timestamp(col).year

        revenue = float(revenue_series[col]) if pd.notna(revenue_series[col]) else None
        net_income = float(net_income_series[col]) if pd.notna(net_income_series[col]) else None

        end_assets = asset_by_year.get(year)
        prev_assets = asset_by_year.get(year - 1)
        end_equity = equity_by_year.get(year)
        prev_equity = equity_by_year.get(year - 1)

        avg_assets = ((end_assets + prev_assets) / 2 if (end_assets and prev_assets)
                      else end_assets)
        avg_equity = ((end_equity + prev_equity) / 2 if (end_equity and prev_equity)
                      else end_equity)

        net_margin = safe_divide(net_income, revenue)
        asset_turnover = safe_divide(revenue, avg_assets)
        leverage = safe_divide(avg_assets, avg_equity)

        roe_computed = None
        if all(v is not None for v in [net_margin, asset_turnover, leverage]):
            roe_computed = net_margin * asset_turnover * leverage

        rows.append({
            "period": period_label,
            "is_consensus": False,
            "net_margin": net_margin,
            "asset_turnover": asset_turnover,
            "leverage": leverage,
            "roe_display": roe_computed,
            "roe_computed": roe_computed,
            "revenue": revenue,
            "net_income": net_income,
            "avg_assets": avg_assets,
            "avg_equity": avg_equity,
        })

    # 컨센서스: forwardEps × shares = forward net income 추정 (한계 있음)
    # 자산/자본은 마지막 actual 그대로 사용
    if forward_eps and last_actual_col is not None:
        shares = info.get("sharesOutstanding")
        if shares:
            forward_net_income = float(forward_eps) * float(shares)
            # forward revenue는 직접 안 줘서, 마지막 actual의 net margin 적용 (추정)
            last_row = rows[-1] if rows else None
            if last_row and last_row["net_margin"]:
                forward_revenue = forward_net_income / last_row["net_margin"]

                # 자산/자본은 마지막 actual 그대로 (보수적)
                forward_avg_assets = last_row["avg_assets"]
                forward_avg_equity = last_row["avg_equity"]

                f_net_margin = last_row["net_margin"]  # 동일 가정
                f_asset_turnover = safe_divide(forward_revenue, forward_avg_assets)
                f_leverage = safe_divide(forward_avg_assets, forward_avg_equity)

                f_roe = None
                if all(v is not None for v in [f_net_margin, f_asset_turnover, f_leverage]):
                    f_roe = f_net_margin * f_asset_turnover * f_leverage

                # 컨센서스 라벨 (마지막 actual + 1년)
                last_year = pd.Timestamp(last_actual_col).year
                rows.append({
                    "period": f"FY{(last_year + 1) % 100:02d}",
                    "is_consensus": True,
                    "net_margin": f_net_margin,
                    "asset_turnover": f_asset_turnover,
                    "leverage": f_leverage,
                    "roe_display": f_roe,
                    "roe_computed": f_roe,
                    "revenue": forward_revenue,
                    "net_income": forward_net_income,
                    "avg_assets": forward_avg_assets,
                    "avg_equity": forward_avg_equity,
                })

    if len(rows) < 2:
        return None

    components_df = pd.DataFrame(rows)
    roe_change = _decompose_roe_change(components_df)
    narrative = _generate_narrative(components_df, roe_change)

    return {
        "components": components_df,
        "roe_change_components": roe_change,
        "narrative": narrative,
        "source_note": "Source: yfinance · US-GAAP · "
                       "Asset/Equity at period-average · "
                       "Consensus year extrapolated from forwardEps "
                       "(net margin held constant — approximation)",
        "country": "US",
    }


# ============================================================
# 동인 분해 (ROE 변화 → 어느 컴포넌트가 주도했나)
# ============================================================
def _decompose_roe_change(components_df: pd.DataFrame) -> dict:
    """
    ROE 변화 동인 분해.

    로그 분해 사용 (Log-decomposition):
        ln(ROE) = ln(margin) + ln(turnover) + ln(leverage)
        → ΔROE 기여도 = (Δln 컴포넌트 / Δln ROE) × Δ ROE

    근데 음수 ROE 등에서 깨질 수 있어서, 더 단순한 방식:
        ΔROE ≈ Δmargin × turnover₀ × leverage₀
              + margin₁ × Δturnover × leverage₀
              + margin₁ × turnover₁ × Δleverage
        (체인룰 근사)

    여기서는 더 직관적인 절대 변화 기준:
        margin_contribution = Δ margin (in p.p.)
        turnover_contribution = Δ asset_turnover (in 배)
        leverage_contribution = Δ leverage (in 배)

    그리고 ΔROE 자체도 계산해서 함께 반환.
    """
    if len(components_df) < 2:
        return {}

    result = {"periods": []}

    for i in range(1, len(components_df)):
        prev = components_df.iloc[i - 1]
        curr = components_df.iloc[i]

        d_margin = _safe_diff(curr["net_margin"], prev["net_margin"])  # in ratio
        d_turnover = _safe_diff(curr["asset_turnover"], prev["asset_turnover"])
        d_leverage = _safe_diff(curr["leverage"], prev["leverage"])
        d_roe = _safe_diff(curr["roe_display"], prev["roe_display"])

        # 상대 기여도 (체인룰 근사)
        # ΔROE ≈ Δm × t × L + m × Δt × L + m × t × ΔL
        m0 = prev["net_margin"]
        t0 = prev["asset_turnover"]
        L0 = prev["leverage"]
        m1 = curr["net_margin"]
        t1 = curr["asset_turnover"]
        L1 = curr["leverage"]

        margin_effect = None
        turnover_effect = None
        leverage_effect = None
        if all(v is not None for v in [d_margin, t0, L0]):
            margin_effect = d_margin * t0 * L0
        if all(v is not None for v in [d_turnover, m1, L0]):
            turnover_effect = m1 * d_turnover * L0
        if all(v is not None for v in [d_leverage, m1, t1]):
            leverage_effect = m1 * t1 * d_leverage

        result["periods"].append({
            "from_period": prev["period"],
            "to_period": curr["period"],
            "d_roe": d_roe,
            "d_margin": d_margin,
            "d_turnover": d_turnover,
            "d_leverage": d_leverage,
            "margin_effect": margin_effect,
            "turnover_effect": turnover_effect,
            "leverage_effect": leverage_effect,
            "is_consensus": curr.get("is_consensus", False),
        })

    return result


# ============================================================
# 한 줄 해설 자동 생성 (옵션 II: 풍부)
# ============================================================
def _generate_narrative(components_df: pd.DataFrame, roe_change: dict) -> str:
    """
    3가지 컴포넌트 다 평가한 풍부한 해설.
    예시:
    "FY24 → FY25 ROE +1.8%p 상승. 마진 +2.1%p 개선이 주도. 자산회전율 보합, 레버리지 +0.03배 미세 증가."
    """
    if not roe_change.get("periods"):
        return ""

    # 최근 두 기간 (보통 마지막 actual → 다음 actual 또는 consensus)
    period_data = roe_change["periods"][-1]

    from_p = period_data["from_period"]
    to_p = period_data["to_period"]
    d_roe = period_data["d_roe"]
    d_margin = period_data["d_margin"]
    d_turnover = period_data["d_turnover"]
    d_leverage = period_data["d_leverage"]
    is_consensus = period_data["is_consensus"]

    parts = []

    # 1) ROE 변화
    if d_roe is not None:
        consensus_label = " (consensus)" if is_consensus else ""
        direction = "rose" if d_roe >= 0 else "fell"
        parts.append(f"{from_p} → {to_p}{consensus_label}: ROE {direction} "
                     f"{abs(d_roe)*100:+.1f}p.p.")

    # 2) 주요 동인 분석
    drivers = []
    if d_margin is not None:
        if abs(d_margin) >= 0.005:  # 0.5%p 이상
            label = "improved" if d_margin >= 0 else "deteriorated"
            drivers.append(("margin", d_margin * 100, label))
    if d_turnover is not None:
        if abs(d_turnover) >= 0.02:  # 0.02배 이상
            label = "improved" if d_turnover >= 0 else "deteriorated"
            drivers.append(("asset turnover", d_turnover, label))
    if d_leverage is not None:
        if abs(d_leverage) >= 0.02:
            label = "increased" if d_leverage >= 0 else "decreased"
            drivers.append(("leverage", d_leverage, label))

    # 주요 동인 정렬 (절대값 큰 순)
    if drivers:
        # 표준화: ROE 영향 크기 기준 정렬 (margin은 % 곱하기 100)
        drivers_with_impact = []
        for name, val, label in drivers:
            if name == "margin":
                impact = abs(val)  # p.p.
            else:
                impact = abs(val) * 10  # 배 단위는 더 큰 영향
            drivers_with_impact.append((impact, name, val, label))
        drivers_with_impact.sort(reverse=True)

        # 주요 동인 (1순위)
        top = drivers_with_impact[0]
        _, top_name, top_val, top_label = top
        if top_name == "margin":
            parts.append(f"Driven by {top_name} {top_label} ({top_val:+.1f}p.p.)")
        else:
            parts.append(f"Driven by {top_name} {top_label} ({top_val:+.2f}x)")

        # 2~3순위 (있으면)
        secondary_parts = []
        for _, name, val, label in drivers_with_impact[1:]:
            if name == "margin":
                secondary_parts.append(f"{name} {label} ({val:+.1f}p.p.)")
            else:
                secondary_parts.append(f"{name} {label} ({val:+.2f}x)")

        if secondary_parts:
            parts.append("Secondary: " + ", ".join(secondary_parts))
    else:
        parts.append("All components ~ flat")

    # 3) 시그널 분류 (옵션 II 마지막 단계)
    signal = _classify_signal(d_margin, d_turnover, d_leverage)
    if signal:
        parts.append(signal)

    return ". ".join(parts) + "."


def _classify_signal(d_margin, d_turnover, d_leverage) -> Optional[str]:
    """
    듀퐁 변화의 의미를 한 단어로 분류.
    """
    if d_margin is None or d_turnover is None or d_leverage is None:
        return None

    margin_up = d_margin > 0.005
    margin_down = d_margin < -0.005
    turnover_up = d_turnover > 0.02
    turnover_down = d_turnover < -0.02
    leverage_up = d_leverage > 0.02

    # 시나리오별 라벨
    if margin_up and turnover_up:
        return "Signal: Operating leverage in action (margin + turnover both improving)"
    if margin_up and not turnover_down and not leverage_up:
        return "Signal: Healthy margin-driven (no balance sheet aggression)"
    if margin_up and leverage_up and not turnover_up:
        return "Signal: Margin + leverage (watch debt levels)"
    if margin_down and turnover_down:
        return "Signal: Deteriorating (margin compression + asset inefficiency)"
    if not margin_up and not turnover_up and leverage_up:
        return "Signal: Leverage-driven ROE (caution — lower quality growth)"
    if margin_down and leverage_up:
        return "Signal: Margin squeeze offset by leverage (warning)"
    return None


# ============================================================
# 헬퍼
# ============================================================
def _safe_at(df: pd.DataFrame, row_name: str, col) -> Optional[float]:
    if df is None or df.empty:
        return None
    if row_name not in df.index:
        return None
    try:
        val = df.at[row_name, col]
        if pd.isna(val):
            return None
        return float(val)
    except (KeyError, ValueError, TypeError):
        return None


def _safe_diff(a, b) -> Optional[float]:
    if a is None or b is None:
        return None
    try:
        return float(a) - float(b)
    except (TypeError, ValueError):
        return None


def _format_year(col) -> str:
    """Timestamp → 'FY25' 형식."""
    try:
        ts = pd.Timestamp(col)
        return f"FY{ts.year % 100:02d}"
    except (TypeError, ValueError):
        return str(col)
