"""
modules/profitability_analysis.py — 수익성 분석 + DuPont 3분해

★ PDF의 핵심 분석 ★
ROE = (순이익/매출) × (매출/자산) × (자산/자본)
    = 순이익률 × 자산회전율 × 재무레버리지

이 셋 중 어느 게 ROE를 끌어올리는지 자동 판정:
- 순이익률 주도형 → "마진 주도형 ★" (가격 결정력)
- 자산회전율 주도형 → "효율성 주도형" (외주/경량 자산)
- 재무레버리지 주도형 → "레버리지 의존형 ⚠"

PDF 예시:
- 삼양식품 vs 농심 → 순이익률 16% vs 5% (해외 매출 단가 상승)
- 에이피알 vs 아모레퍼시픽 → 자산회전율 128% vs 57% (외주 vs 자체 생산)
- 애플 → 자사주 매입으로 레버리지 활용

표준 출력 스키마:
{
    "metrics": {
        "roe": ..., "roa": ...,
        "net_margin": ..., "asset_turnover": ..., "leverage": ...,
        "dupont": {...},
    },
    "interpretation": "...",
    "flags": [...],
    "type": "마진 주도형" | "효율성 주도형" | "레버리지 의존형" | "균형형",
}
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd

from config import DUPONT_THRESHOLDS, DUPONT_BASELINE, VALUATION_THRESHOLDS
from modules.financial_metrics import (
    INCOME_ROW_ALIASES, BALANCE_ROW_ALIASES,
    ttm_sum, ttm_avg, get_row_series, balance,
    gross_margin, operating_margin, net_margin,
)
from utils.validation import safe_divide


def analyze_profitability(data: dict) -> dict:
    """
    수익성 종합 분석. DuPont 3분해 포함.

    Args:
        data: data_loader.load_company_data() 결과

    Returns:
        표준 출력 스키마 (+ "type" 키)
    """
    income_q = data.get("income_quarterly", pd.DataFrame())
    balance_q = data.get("balance_quarterly", pd.DataFrame())

    flags = []

    # ============================================================
    # 1. TTM 손익 + 평균 잔액 추출
    # ============================================================
    revenue = ttm_sum(income_q, "revenue", INCOME_ROW_ALIASES)
    net_income = ttm_sum(income_q, "net_income", INCOME_ROW_ALIASES)
    avg_assets = ttm_avg(balance_q, "total_assets", BALANCE_ROW_ALIASES)
    avg_equity = ttm_avg(balance_q, "stockholders_equity", BALANCE_ROW_ALIASES)

    # ============================================================
    # 2. 핵심 비율
    # ============================================================
    roe = safe_divide(net_income, avg_equity)
    roa = safe_divide(net_income, avg_assets)
    npm = safe_divide(net_income, revenue)                  # 순이익률
    asset_turnover = safe_divide(revenue, avg_assets)        # 자산회전율
    leverage = safe_divide(avg_assets, avg_equity)           # 재무레버리지

    gpm = gross_margin(income_q, use_ttm=True)
    opm = operating_margin(income_q, use_ttm=True)

    # ============================================================
    # 3. DuPont 분해 검증
    #    ROE = NPM × Asset Turnover × Leverage
    # ============================================================
    dupont_check = None
    if all(v is not None for v in [npm, asset_turnover, leverage]):
        dupont_calc = npm * asset_turnover * leverage
        # ROE와 dupont_calc는 (이론상) 같아야 함. 차이는 평균/말잔 사용 차이 등.
        dupont_check = {
            "calculated_roe": dupont_calc,
            "reported_roe":   roe,
            "deviation":      (dupont_calc - roe) if roe is not None else None,
        }

    # ============================================================
    # 4. 주도형 판정 — PDF의 핵심
    # ============================================================
    dupont_type, contributions = _classify_dupont_type(npm, asset_turnover, leverage)

    # ============================================================
    # 5. ROE > COE 체크 (PDF: COE보다 ROE가 커야 투자가치)
    # ============================================================
    coe = VALUATION_THRESHOLDS["coe_default"]
    roe_above_coe = None
    if roe is not None:
        roe_above_coe = roe > coe

    # ============================================================
    # 6. Flag 생성
    # ============================================================
    if roe is not None:
        if roe < 0:
            flags.append({
                "type": "negative_roe", "severity": "warning",
                "msg": f"ROE 음수 ({roe:.1%}) - 적자 상태",
            })
        elif roe < coe:
            flags.append({
                "type": "roe_below_coe", "severity": "warning",
                "msg": f"ROE ({roe:.1%}) < 자기자본비용 ({coe:.0%}) - 가치 파괴 가능성",
            })

    if leverage is not None and leverage > DUPONT_THRESHOLDS["max_leverage_safe"]:
        flags.append({
            "type": "high_leverage", "severity": "warning",
            "msg": f"재무레버리지 {leverage:.2f}배 — 안전 기준({DUPONT_THRESHOLDS['max_leverage_safe']:.1f}배) 초과",
        })

    if dupont_type == "레버리지 의존형":
        flags.append({
            "type": "leverage_driven", "severity": "warning",
            "msg": "ROE가 레버리지에 크게 의존 - 영업 수익성 질적 평가 필요",
        })
    elif dupont_type == "마진 주도형 ★":
        flags.append({
            "type": "margin_driven", "severity": "good",
            "msg": "마진 주도형 ROE - 가격 결정력 강함",
        })

    # ============================================================
    # 7. 해석
    # ============================================================
    interpretation = _build_interpretation(
        roe=roe, roa=roa, npm=npm, asset_turnover=asset_turnover,
        leverage=leverage, dupont_type=dupont_type, gpm=gpm, opm=opm,
        roe_above_coe=roe_above_coe,
    )

    return {
        "metrics": {
            "roe":             roe,
            "roa":             roa,
            "net_margin":      npm,
            "asset_turnover":  asset_turnover,
            "leverage":        leverage,
            "gross_margin":    gpm,
            "operating_margin": opm,
            "roe_above_coe":   roe_above_coe,
            "coe_assumed":     coe,
            "dupont": {
                "net_margin_contribution":     contributions.get("margin"),
                "asset_turnover_contribution": contributions.get("efficiency"),
                "leverage_contribution":       contributions.get("leverage"),
                "check": dupont_check,
            },
        },
        "type": dupont_type,
        "interpretation": interpretation,
        "flags": flags,
    }


# ============================================================
# 주도형 판정
# ============================================================
def _classify_dupont_type(
    npm: Optional[float],
    asset_turnover: Optional[float],
    leverage: Optional[float],
) -> tuple[str, dict]:
    """
    DuPont 3요소의 ROE 기여도를 "베이스라인 대비 편차"로 분해해 주도형 판정.

    수학적 근거:
        ROE = NPM × AT × Lev
        log(ROE / baseline_ROE) = log(NPM/base) + log(AT/base) + log(Lev/base)
        각 항의 |log| 값이 해당 요소가 ROE를 베이스라인 대비 얼마나
        위/아래로 끌어당겼는지를 의미.

    이 방식이 정확한 이유:
        - NPM=0.05일 때 |log(0.05)|=3.0이라 단순 |log|로는 마진 기여가 과대평가됨
        - 베이스라인(NPM=0.08) 대비 편차로 보면 |log(0.05/0.08)|=0.47로 정상화
        - 같은 0.05 마진이라도 "평균 대비 약함"으로 평가됨

    Returns:
        (유형명, 기여도 dict)
    """
    contributions = {"margin": None, "efficiency": None, "leverage": None}

    if any(v is None for v in [npm, asset_turnover, leverage]):
        return "데이터 부족", contributions
    if npm <= 0 or asset_turnover <= 0 or leverage <= 0:
        return "데이터 부족", contributions

    base_npm = DUPONT_BASELINE["net_margin"]
    base_at = DUPONT_BASELINE["asset_turnover"]
    base_lev = DUPONT_BASELINE["leverage"]

    # 베이스라인 대비 편차의 절댓값
    log_npm = abs(math.log(npm / base_npm))
    log_at = abs(math.log(asset_turnover / base_at))
    log_lev = abs(math.log(leverage / base_lev))
    total = log_npm + log_at + log_lev

    if total == 0:
        return "균형형", contributions

    margin_share = log_npm / total
    efficiency_share = log_at / total
    leverage_share = log_lev / total

    contributions = {
        "margin":     margin_share,
        "efficiency": efficiency_share,
        "leverage":   leverage_share,
    }

    # 추가 안전장치: 레버리지가 베이스라인보다 훨씬 크면 의존형 판정 우선
    # (베이스라인 대비 2배 이상 + 비중 임계 충족)
    if leverage / base_lev >= 2.0 and leverage_share >= DUPONT_THRESHOLDS["leverage_driven_warning"]:
        return "레버리지 의존형", contributions

    # 마진이 베이스라인보다 강하면서 비중도 큼
    if npm > base_npm and margin_share >= DUPONT_THRESHOLDS["margin_driven_min"]:
        return "마진 주도형 ★", contributions

    # 자산회전율이 베이스라인보다 강하면서 비중도 큼
    if asset_turnover > base_at and efficiency_share >= DUPONT_THRESHOLDS["efficiency_driven_min"]:
        return "효율성 주도형", contributions

    # 레버리지 비중만 크면서 베이스라인보다 큼 (위 우선조건 못 통과한 경우)
    if leverage > base_lev and leverage_share >= DUPONT_THRESHOLDS["leverage_driven_warning"]:
        return "레버리지 의존형", contributions

    return "균형형", contributions


# ============================================================
# 해석 문자열
# ============================================================
def _build_interpretation(
    roe, roa, npm, asset_turnover, leverage,
    dupont_type, gpm, opm, roe_above_coe,
) -> str:
    parts = []

    if roe is not None:
        parts.append(f"ROE {roe:.1%}")
    if roa is not None:
        parts.append(f"ROA {roa:.1%}")

    if npm is not None and asset_turnover is not None and leverage is not None:
        parts.append(
            f"= 순이익률 {npm:.1%} × 자산회전율 {asset_turnover:.2f} × 레버리지 {leverage:.2f}배"
        )

    line1 = ", ".join(parts) + "."
    lines = [line1]

    # 주도형
    if dupont_type and dupont_type != "데이터 부족":
        type_explanations = {
            "마진 주도형 ★":     "가격 결정력이 강함. 브랜드/특허/스위칭코스트 보유 가능성.",
            "효율성 주도형":     "자산 대비 매출 회전이 빠름. 외주/경량 자산 모델일 가능성.",
            "레버리지 의존형":   "차입 등 재무 지렛대로 ROE 부양. 영업 수익성 질적 검토 필요.",
            "균형형":           "세 요소가 균형 있게 기여. 안정적 비즈니스 모델.",
        }
        explanation = type_explanations.get(dupont_type, "")
        lines.append(f"유형: {dupont_type} — {explanation}")

    # GPM/OPM 보조 정보
    margin_parts = []
    if gpm is not None:
        margin_parts.append(f"GPM {gpm:.1%}")
    if opm is not None:
        margin_parts.append(f"OPM {opm:.1%}")
    if margin_parts:
        lines.append("마진 구조: " + ", ".join(margin_parts) + ".")

    # ROE vs COE
    if roe_above_coe is True:
        lines.append("ROE > 자기자본비용 → 가치 창출 ✓")
    elif roe_above_coe is False:
        lines.append("ROE < 자기자본비용 → 가치 파괴 위험 ⚠")

    return " ".join(lines)


# ============================================================
# 5년 시계열 ROE 분해 (UI 차트용)
# ============================================================
def get_roe_timeseries(data: dict, years: int = 5) -> pd.DataFrame:
    """
    연간 DuPont 3분해 시계열.
    UI에서 5년 추세 차트로 보여주기 위함.

    Returns:
        DataFrame with columns: year, roe, net_margin, asset_turnover, leverage
    """
    income_a = data.get("income_annual", pd.DataFrame())
    balance_a = data.get("balance_annual", pd.DataFrame())

    if income_a.empty or balance_a.empty:
        return pd.DataFrame()

    rev_series = get_row_series(income_a, INCOME_ROW_ALIASES["revenue"])
    ni_series = get_row_series(income_a, INCOME_ROW_ALIASES["net_income"])
    asset_series = get_row_series(balance_a, BALANCE_ROW_ALIASES["total_assets"])
    equity_series = get_row_series(balance_a, BALANCE_ROW_ALIASES["stockholders_equity"])

    rows = []
    common_cols = sorted(
        set(rev_series.index) & set(ni_series.index)
        & set(asset_series.index) & set(equity_series.index),
        reverse=True,
    )[:years]

    for col in common_cols:
        try:
            rev = float(rev_series[col])
            ni = float(ni_series[col])
            assets = float(asset_series[col])
            equity = float(equity_series[col])

            if rev > 0 and assets > 0 and equity > 0:
                rows.append({
                    "year":           pd.Timestamp(col).year,
                    "roe":            ni / equity,
                    "net_margin":     ni / rev,
                    "asset_turnover": rev / assets,
                    "leverage":       assets / equity,
                })
        except (TypeError, ValueError):
            continue

    return pd.DataFrame(rows).sort_values("year").reset_index(drop=True)
