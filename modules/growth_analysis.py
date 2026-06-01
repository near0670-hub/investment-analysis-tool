"""
modules/growth_analysis.py — 성장성 분석

핵심 출력:
1. 매출 YoY (분기/연간)
2. EPS YoY (분기/연간)
3. 3년 EPS / 매출 CAGR
4. 분기 가속 여부 (직전 분기 < 당분기)
5. ★ 매출-EPS 갭 분해 (영업레버리지 / 비용절감 / 자사주 효과)

PDF의 분석 철학 반영:
- EPS 성장이 매출 성장보다 클 때:
    1) 영업레버리지 (마진 확대)
    2) 비용절감
    3) 자사주 매입 (주식 수 감소)
    이 셋 중 어디서 왔는지 정량 분해

표준 출력 스키마:
{
    "metrics": {...},
    "interpretation": "...",
    "flags": [...],
}
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from modules.financial_metrics import (
    INCOME_ROW_ALIASES, BALANCE_ROW_ALIASES,
    get_row_series, get_row_value, income, balance,
)
from utils.validation import safe_growth, safe_cagr, safe_divide


def analyze_growth(data: dict) -> dict:
    """
    성장성 종합 분석.

    Args:
        data: data_loader.load_company_data() 결과 dict

    Returns:
        표준 출력 스키마
    """
    income_q = data.get("income_quarterly", pd.DataFrame())
    income_a = data.get("income_annual", pd.DataFrame())
    balance_q = data.get("balance_quarterly", pd.DataFrame())

    flags = []

    # ============================================================
    # 1. 분기 매출/EPS YoY
    # ============================================================
    qtr_revenue = _quarterly_yoy(income_q, "revenue")
    qtr_eps = _quarterly_yoy(income_q, "diluted_eps")
    if qtr_eps["current_yoy"] is None:
        # Diluted 없으면 Basic으로 fallback
        qtr_eps = _quarterly_yoy(income_q, "basic_eps")

    # ============================================================
    # 2. 분기 가속 여부 (CAN SLIM의 C 조건 중 하나)
    # ============================================================
    eps_acceleration = _check_acceleration(
        qtr_eps["current_yoy"], qtr_eps["prior_yoy"]
    )
    revenue_acceleration = _check_acceleration(
        qtr_revenue["current_yoy"], qtr_revenue["prior_yoy"]
    )

    # ============================================================
    # 3. 연간 3년 CAGR
    # ============================================================
    revenue_cagr_3y = _annual_cagr(income_a, "revenue", years=3)
    eps_cagr_3y = _annual_cagr_eps(income_a, years=3)

    # ============================================================
    # 4. 최근 1년 순이익 사상 최고치 여부 (CAN SLIM의 A 조건)
    # ============================================================
    net_income_all_time_high = _check_all_time_high(income_a, "net_income")

    # ============================================================
    # 5. ★ 매출-EPS 갭 분해 (PDF 핵심)
    # ============================================================
    gap_decomp = _decompose_revenue_eps_gap(
        data=data,
        revenue_yoy=qtr_revenue["current_yoy"],
        eps_yoy=qtr_eps["current_yoy"],
    )

    # ============================================================
    # 6. Flag 생성
    # ============================================================
    if qtr_revenue["current_yoy"] is not None and qtr_revenue["current_yoy"] < 0:
        flags.append({
            "type": "revenue_decline",
            "severity": "warning",
            "msg": f"분기 매출 역성장 ({qtr_revenue['current_yoy']:.1%})",
        })

    if qtr_eps["current_yoy"] is not None and qtr_eps["current_yoy"] < 0:
        flags.append({
            "type": "eps_decline",
            "severity": "warning",
            "msg": f"분기 EPS 역성장 ({qtr_eps['current_yoy']:.1%})",
        })

    # 매출 < EPS 가 큰 폭이면 일회성 의심
    if gap_decomp.get("gap_pct") is not None and gap_decomp["gap_pct"] > 0.20:
        flags.append({
            "type": "eps_exceeds_revenue_growth",
            "severity": "info",
            "msg": (
                f"EPS 성장({qtr_eps['current_yoy']:.1%})이 매출 성장"
                f"({qtr_revenue['current_yoy']:.1%})보다 +{gap_decomp['gap_pct']:.1%}p 큼 "
                f"→ {gap_decomp.get('primary_driver', '분해 데이터 부족')}"
            ),
        })

    # 매출 > EPS 면 마진 압박
    if gap_decomp.get("gap_pct") is not None and gap_decomp["gap_pct"] < -0.10:
        flags.append({
            "type": "margin_pressure",
            "severity": "warning",
            "msg": (
                f"EPS 성장({qtr_eps['current_yoy']:.1%})이 매출 성장"
                f"({qtr_revenue['current_yoy']:.1%})보다 낮음 "
                f"→ 마진 압박 또는 비용 증가"
            ),
        })

    # 가속 여부 플래그
    if eps_acceleration is True:
        flags.append({"type": "eps_accelerating", "severity": "good",
                      "msg": "EPS 성장률 가속 (직전 분기 < 당분기)"})
    elif eps_acceleration is False:
        flags.append({"type": "eps_decelerating", "severity": "info",
                      "msg": "EPS 성장률 둔화"})

    # ============================================================
    # 7. 해석 문자열
    # ============================================================
    interpretation = _build_interpretation(
        qtr_revenue, qtr_eps, revenue_cagr_3y, eps_cagr_3y,
        eps_acceleration, gap_decomp, net_income_all_time_high,
    )

    return {
        "metrics": {
            "quarterly_revenue_yoy":  qtr_revenue["current_yoy"],
            "quarterly_eps_yoy":      qtr_eps["current_yoy"],
            "prior_revenue_yoy":      qtr_revenue["prior_yoy"],
            "prior_eps_yoy":          qtr_eps["prior_yoy"],
            "eps_accelerating":       eps_acceleration,
            "revenue_accelerating":   revenue_acceleration,
            "revenue_cagr_3y":        revenue_cagr_3y,
            "eps_cagr_3y":            eps_cagr_3y,
            "net_income_all_time_high": net_income_all_time_high,
            "gap_decomposition":      gap_decomp,
        },
        "interpretation": interpretation,
        "flags": flags,
    }


# ============================================================
# 내부 헬퍼
# ============================================================
def _quarterly_yoy(income_q: pd.DataFrame, key: str) -> dict:
    """
    분기 YoY (현재 분기 vs 4분기 전).

    Returns:
        {
            "current_yoy":   당 분기 YoY 성장률,
            "prior_yoy":     직전 분기 YoY (가속 여부 판단용),
            "current_value": 당기 값,
            "prior_value":   4분기 전 값,
        }
    """
    aliases = INCOME_ROW_ALIASES.get(key, [])
    series = get_row_series(income_q, aliases)

    if series.empty or len(series) < 5:
        # 최소 5분기 데이터 필요 (YoY 계산 + 직전 분기 YoY)
        return {"current_yoy": None, "prior_yoy": None,
                "current_value": None, "prior_value": None}

    # series는 yfinance에서 최근이 인덱스 0
    current = series.iloc[0]
    yoy_base = series.iloc[4] if len(series) > 4 else None
    current_yoy = safe_growth(current, yoy_base) if pd.notna(current) else None

    # 직전 분기 YoY
    if len(series) >= 6:
        prior = series.iloc[1]
        prior_yoy_base = series.iloc[5]
        prior_yoy = safe_growth(prior, prior_yoy_base) if pd.notna(prior) else None
    else:
        prior_yoy = None

    return {
        "current_yoy":   current_yoy,
        "prior_yoy":     prior_yoy,
        "current_value": float(current) if pd.notna(current) else None,
        "prior_value":   float(yoy_base) if yoy_base is not None and pd.notna(yoy_base) else None,
    }


def _check_acceleration(current_yoy: Optional[float],
                       prior_yoy: Optional[float]) -> Optional[bool]:
    """
    성장 가속 여부.
    True  = 가속 (CAN SLIM의 C 조건 만족)
    False = 둔화
    None  = 판단 불가
    """
    if current_yoy is None or prior_yoy is None:
        return None
    return current_yoy > prior_yoy


def _annual_cagr(income_a: pd.DataFrame, key: str, years: int = 3) -> Optional[float]:
    """연간 CAGR."""
    aliases = INCOME_ROW_ALIASES.get(key, [])
    series = get_row_series(income_a, aliases).dropna()

    if len(series) <= years:
        return None

    # series는 최신이 인덱스 0
    end_value = series.iloc[0]
    start_value = series.iloc[years]
    return safe_cagr(end_value, start_value, years)


def _annual_cagr_eps(income_a: pd.DataFrame, years: int = 3) -> Optional[float]:
    """EPS CAGR (Diluted 우선, 없으면 Basic)."""
    cagr = _annual_cagr(income_a, "diluted_eps", years)
    if cagr is not None:
        return cagr
    return _annual_cagr(income_a, "basic_eps", years)


def _check_all_time_high(income_a: pd.DataFrame, key: str) -> Optional[bool]:
    """최근 연간 값이 사상 최고치인지."""
    aliases = INCOME_ROW_ALIASES.get(key, [])
    series = get_row_series(income_a, aliases).dropna()

    if series.empty:
        return None

    current = series.iloc[0]
    historical_max = series.max()
    return bool(current >= historical_max)


def _decompose_revenue_eps_gap(
    data: dict,
    revenue_yoy: Optional[float],
    eps_yoy: Optional[float],
) -> dict:
    """
    ★ PDF 핵심 분석 ★

    EPS 성장 - 매출 성장 = ?
    이 차이를 다음 3가지로 분해:
      1) 영업레버리지 (영업이익률 변화)
      2) 비영업 효과 (세금, 이자, 일회성)
      3) 자사주 효과 (주식 수 감소)

    분해식:
        EPS = (NI / Shares)
        EPS Growth ≈ Revenue Growth + Margin Effect + Non-op Effect + Share Effect

    Returns:
        {
            "gap_pct":           EPS Growth - Revenue Growth,
            "margin_contribution": 영업레버리지 기여 (영업이익률 변화),
            "share_contribution":  자사주 기여 (주식수 변화),
            "residual":            그 외 (세금/이자/일회성),
            "primary_driver":      가장 큰 기여 요인,
        }
    """
    if revenue_yoy is None or eps_yoy is None:
        return {"gap_pct": None}

    gap = eps_yoy - revenue_yoy

    income_q = data.get("income_quarterly", pd.DataFrame())

    # 1. 영업이익률 변화 기여
    margin_contribution = _operating_margin_contribution(income_q)

    # 2. 자사주 효과 (주식 수 YoY 감소가 EPS에 미치는 기여)
    share_contribution = _share_count_contribution(data)

    # 3. 잔차 = gap - margin - share
    if margin_contribution is not None and share_contribution is not None:
        residual = gap - margin_contribution - share_contribution
    else:
        residual = None

    # 4. Primary driver 결정
    contributions = {
        "영업레버리지": margin_contribution,
        "자사주 효과":   share_contribution,
        "비영업 효과":   residual,
    }
    valid = {k: v for k, v in contributions.items() if v is not None}

    if valid:
        primary = max(valid.items(), key=lambda kv: abs(kv[1]))
        primary_driver = f"{primary[0]} 주도 ({primary[1]:+.1%}p)"
    else:
        primary_driver = "분해 데이터 부족"

    return {
        "gap_pct":             gap,
        "margin_contribution": margin_contribution,
        "share_contribution":  share_contribution,
        "residual":            residual,
        "primary_driver":      primary_driver,
    }


def _operating_margin_contribution(income_q: pd.DataFrame) -> Optional[float]:
    """
    영업이익률 변화 기여 분.
    = (당기 OPM - 전년동기 OPM) / 전년동기 OPM 의 EPS 기여

    근사적으로 (당기 OPM / 전년동기 OPM - 1) * (전년동기 OPM의 영향력).
    여기서는 단순화해서: 당기 OPM 변화율을 그대로 기여로 봄.
    """
    aliases_rev = INCOME_ROW_ALIASES["revenue"]
    aliases_op = INCOME_ROW_ALIASES["operating_income"]

    rev_series = get_row_series(income_q, aliases_rev)
    op_series = get_row_series(income_q, aliases_op)

    if rev_series.empty or op_series.empty or len(rev_series) < 5 or len(op_series) < 5:
        return None

    # 당기 OPM
    current_rev = rev_series.iloc[0]
    current_op = op_series.iloc[0]
    if pd.isna(current_rev) or pd.isna(current_op) or current_rev == 0:
        return None
    current_opm = current_op / current_rev

    # 전년동기 OPM
    prior_rev = rev_series.iloc[4]
    prior_op = op_series.iloc[4]
    if pd.isna(prior_rev) or pd.isna(prior_op) or prior_rev == 0:
        return None
    prior_opm = prior_op / prior_rev

    # 마진 변화 (절대 차이)
    return float(current_opm - prior_opm)


def _share_count_contribution(data: dict) -> Optional[float]:
    """
    자사주 효과: 주식 수 YoY 변화가 EPS 성장에 기여하는 정도.
    주식 수 -5% → EPS +5.3% 효과 (1/0.95 - 1)
    """
    income_q = data.get("income_quarterly", pd.DataFrame())

    # 분기 데이터에서 주식 수가 직접 안 나오는 경우 많음
    # → 분기 net_income / 분기 EPS 로 역산
    aliases_ni = INCOME_ROW_ALIASES["net_income"]
    aliases_eps = INCOME_ROW_ALIASES["diluted_eps"]

    ni_series = get_row_series(income_q, aliases_ni)
    eps_series = get_row_series(income_q, aliases_eps)

    if eps_series.empty or ni_series.empty:
        # Basic EPS fallback
        eps_series = get_row_series(income_q, INCOME_ROW_ALIASES["basic_eps"])

    if eps_series.empty or ni_series.empty or len(eps_series) < 5 or len(ni_series) < 5:
        return None

    # 주식 수 = NI / EPS (역산)
    def _shares(ni: float, eps: float) -> Optional[float]:
        if pd.isna(ni) or pd.isna(eps) or eps == 0:
            return None
        return ni / eps

    current_shares = _shares(ni_series.iloc[0], eps_series.iloc[0])
    prior_shares = _shares(ni_series.iloc[4], eps_series.iloc[4])

    if current_shares is None or prior_shares is None or current_shares == 0:
        return None

    # EPS 기여 = (prior_shares / current_shares) - 1
    # 주식 수가 줄면 양수 (EPS에 +기여)
    return float(prior_shares / current_shares - 1)


def _build_interpretation(
    qtr_revenue: dict, qtr_eps: dict,
    revenue_cagr_3y: Optional[float], eps_cagr_3y: Optional[float],
    eps_acceleration: Optional[bool], gap_decomp: dict,
    net_income_all_time_high: Optional[bool],
) -> str:
    """사람이 읽기 좋은 해석 문자열 생성."""
    lines = []

    # 분기 성장
    if qtr_revenue["current_yoy"] is not None and qtr_eps["current_yoy"] is not None:
        lines.append(
            f"분기 매출 YoY {qtr_revenue['current_yoy']:+.1%}, "
            f"EPS YoY {qtr_eps['current_yoy']:+.1%}."
        )

    # 가속 여부
    if eps_acceleration is True:
        lines.append("EPS 성장률이 직전 분기 대비 가속 중 ✓")
    elif eps_acceleration is False:
        lines.append("EPS 성장률이 직전 분기 대비 둔화")

    # 연간 CAGR
    cagr_parts = []
    if revenue_cagr_3y is not None:
        cagr_parts.append(f"매출 {revenue_cagr_3y:+.1%}")
    if eps_cagr_3y is not None:
        cagr_parts.append(f"EPS {eps_cagr_3y:+.1%}")
    if cagr_parts:
        lines.append(f"최근 3년 연평균 ({', '.join(cagr_parts)}).")

    # 사상 최고치
    if net_income_all_time_high is True:
        lines.append("최근 1년 순이익 사상 최고치 ✓")
    elif net_income_all_time_high is False:
        lines.append("최근 1년 순이익이 사상 최고치는 아님")

    # 갭 분해
    if gap_decomp.get("gap_pct") is not None:
        gap = gap_decomp["gap_pct"]
        driver = gap_decomp.get("primary_driver", "")
        if abs(gap) > 0.05:
            sign = "초과" if gap > 0 else "미달"
            lines.append(f"EPS 성장이 매출 대비 {abs(gap):.1%}p {sign} — {driver}.")

    return " ".join(lines) if lines else "성장성 분석에 필요한 데이터가 부족합니다."
