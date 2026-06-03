"""
modules/valuation_analysis.py — 밸류에이션 분석 + PEG 3변형 + Trap Detection

★ 이 도구의 메인 시그널 ★

핵심 출력:
1. PER (TTM), Forward PER (1Y, 2Y)
2. PBR, PSR, EV/EBITDA
3. PEG 3변형 (TTM / Forward 1Y / Forward 2Y) ★
4. Trap Detection (밸류에이션 함정 자동 감지)

PDF 분석 철학 반영:
- PER 낮다고 무조건 저평가 아님 → Trap Detection으로 함정 감지
- 주가 = 이익 × 멀티플 프레임
- 성장률 검증: 과도하게 높은 성장률(>50%)은 신뢰성 의심
- 매출-EPS 갭 분해 결과를 참조해서 일회성 이익 식별

표준 출력 스키마:
{
    "metrics": {
        "per_ttm": ..., "forward_per_1y": ..., "forward_per_2y": ...,
        "pbr": ..., "psr": ..., "ev_ebitda": ...,
        "peg_ttm":         {"value": ..., "verdict": ..., "growth_used": ..., "note": ...},
        "peg_forward_1y":  {"value": ..., "verdict": ..., "growth_used": ..., "note": ...},
        "peg_forward_2y":  {"value": ..., "verdict": ..., "growth_used": ..., "note": ...},  # ★
        "growth_used_for_main_peg": ...,
    },
    "interpretation": "...",
    "flags": [
        {"type": "cycle_peak", "severity": "warning", "msg": "..."},
        ...
    ],
}
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from config import (
    PEG_THRESHOLDS,
    PEG_TRAP_RULES,
    VALUATION_THRESHOLDS,
)
from modules.financial_metrics import (
    INCOME_ROW_ALIASES, BALANCE_ROW_ALIASES,
    ttm_sum, ttm_avg, ttm_latest, balance, income,
    get_row_series, ebitda, net_debt,
)
from utils.validation import safe_divide, safe_growth, safe_cagr


# ============================================================
# 메인 분석 함수
# ============================================================
def analyze_valuation(
    data: dict,
    growth_result: Optional[dict] = None,
    user_forward_eps_1y: Optional[float] = None,
    user_forward_eps_2y: Optional[float] = None,
) -> dict:
    """
    밸류에이션 종합 분석 + PEG 3변형 + Trap Detection.

    Args:
        data: data_loader.load_company_data() 결과
        growth_result: growth_analysis.analyze_growth() 결과 (Trap 4,5 체크용)
        user_forward_eps_1y: 한국 종목용 — 향후 1년 EPS 예상값 (애널리스트 컨센서스)
        user_forward_eps_2y: 한국 종목용 — 2년 후 EPS 예상값

    Returns:
        표준 분석 스키마

    Note:
        한국 종목은 yfinance가 Forward EPS를 거의 안 주므로 user_*_eps_*y 인자로
        사용자가 애널리스트 리포트의 추정치를 직접 입력 가능.
    """
    info = data.get("info", {})
    income_q = data.get("income_quarterly", pd.DataFrame())
    income_a = data.get("income_annual", pd.DataFrame())
    balance_q = data.get("balance_quarterly", pd.DataFrame())
    cashflow_q = data.get("cashflow_quarterly", pd.DataFrame())
    meta = data.get("meta", {})

    flags = []

    # ============================================================
    # 1. 기본 가격/멀티플 데이터 수집
    # ============================================================
    market_cap = meta.get("market_cap")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")

    # TTM EPS — 분기 4개 합산이 가장 정확
    eps_ttm = _get_ttm_eps(income_q, info)

    # Forward EPS — 자동 추출 우선, 없으면 사용자 입력
    forward_eps_1y = info.get("forwardEps")
    if not _is_valid_number(forward_eps_1y):
        forward_eps_1y = user_forward_eps_1y

    # 2Y forward는 자동 추출이 거의 안 되므로 사용자 입력 우선
    forward_eps_2y = user_forward_eps_2y

    # ============================================================
    # 2. PER / Forward PER 계산
    # ============================================================
    per_ttm = safe_divide(current_price, eps_ttm) if (current_price and eps_ttm and eps_ttm > 0) else None
    forward_per_1y = safe_divide(current_price, forward_eps_1y) if (current_price and forward_eps_1y and forward_eps_1y > 0) else None
    forward_per_2y = safe_divide(current_price, forward_eps_2y) if (current_price and forward_eps_2y and forward_eps_2y > 0) else None

    # ============================================================
    # 3. PBR / PSR / EV/EBITDA
    # ============================================================
    book_value = balance(balance_q, "stockholders_equity")
    revenue_ttm = ttm_sum(income_q, "revenue", INCOME_ROW_ALIASES)
    ebitda_ttm = ebitda(income_q, cashflow_q, use_ttm=True)
    nd = net_debt(balance_q)
    ev = (market_cap + nd) if (market_cap and nd is not None) else None

    pbr = safe_divide(market_cap, book_value)
    psr = safe_divide(market_cap, revenue_ttm)
    ev_ebitda = safe_divide(ev, ebitda_ttm) if (ev and ebitda_ttm and ebitda_ttm > 0) else None

    # ============================================================
    # 4. ★ PEG 3변형 계산 ★
    # ============================================================
    # 4-1) PEG (TTM) = TTM PER / 과거 2년 EPS CAGR
    growth_past_2y = _calculate_eps_cagr_past(income_a, years=2)
    peg_ttm = _calculate_peg(per_ttm, growth_past_2y, label="TTM (과거 2년)")

    # 4-2) PEG (Forward 1Y) = Forward PER (NTM) / 향후 1년 EPS 성장률
    growth_fwd_1y = safe_growth(forward_eps_1y, eps_ttm) if eps_ttm else None
    peg_forward_1y = _calculate_peg(forward_per_1y, growth_fwd_1y, label="Forward 1Y")

    # 4-3) PEG (Forward 2Y) = Forward PER / 향후 2년 EPS CAGR ★ 메인
    growth_fwd_2y = safe_cagr(forward_eps_2y, eps_ttm, 2) if eps_ttm else None
    peg_forward_2y = _calculate_peg(forward_per_2y, growth_fwd_2y, label="Forward 2Y")

    # ============================================================
    # 5. ROE > COE (PDF 분석 철학)
    # ============================================================
    avg_equity = ttm_avg(balance_q, "stockholders_equity", BALANCE_ROW_ALIASES)
    net_income_ttm = ttm_sum(income_q, "net_income", INCOME_ROW_ALIASES)
    roe_ttm = safe_divide(net_income_ttm, avg_equity)
    coe = VALUATION_THRESHOLDS["coe_default"]
    roe_above_coe = (roe_ttm > coe) if roe_ttm is not None else None

    # ============================================================
    # 6. ★ Trap Detection ★
    # ============================================================
    flags.extend(_detect_traps(
        peg_ttm=peg_ttm,
        peg_fwd_1y=peg_forward_1y,
        peg_fwd_2y=peg_forward_2y,
        growth_fwd_2y=growth_fwd_2y,
        growth_result=growth_result,
        sector_internal=meta.get("sector_internal"),
        operating_margin_current=_get_current_operating_margin(income_q),
        operating_margin_historical_max=_get_historical_max_operating_margin(income_a),
    ))

    # ============================================================
    # 7. PER vs 업종 평균 (단순 비교, 업종 데이터 없으면 스킵)
    # ============================================================
    # Phase 2에서 peer_comparison으로 정교화. MVP는 절대 수준만.

    # ============================================================
    # 8. 해석 문자열
    # ============================================================
    interpretation = _build_interpretation(
        per_ttm=per_ttm,
        forward_per_2y=forward_per_2y,
        peg_ttm=peg_ttm,
        peg_forward_1y=peg_forward_1y,
        peg_forward_2y=peg_forward_2y,
        pbr=pbr, psr=psr, ev_ebitda=ev_ebitda,
        roe_above_coe=roe_above_coe, roe=roe_ttm, coe=coe,
        n_traps=len([f for f in flags if f["severity"] == "warning"]),
    )

    return {
        "metrics": {
            # 기본 멀티플
            "per_ttm":        per_ttm,
            "forward_per_1y": forward_per_1y,
            "forward_per_2y": forward_per_2y,
            "pbr":            pbr,
            "psr":            psr,
            "ev_ebitda":      ev_ebitda,

            # PEG 3변형
            "peg_ttm":         peg_ttm,
            "peg_forward_1y":  peg_forward_1y,
            "peg_forward_2y":  peg_forward_2y,
            "main_peg":        peg_forward_2y,  # 메인 시그널 (Forward 2Y)

            # 보조
            "roe_ttm":         roe_ttm,
            "coe_assumed":     coe,
            "roe_above_coe":   roe_above_coe,

            # 사용된 인풋 (투명성)
            "inputs": {
                "current_price":     current_price,
                "eps_ttm":           eps_ttm,
                "forward_eps_1y":    forward_eps_1y,
                "forward_eps_2y":    forward_eps_2y,
                "forward_eps_1y_source": "yfinance" if info.get("forwardEps") else ("user_input" if user_forward_eps_1y else None),
                "forward_eps_2y_source": "user_input" if user_forward_eps_2y else None,
            },
        },
        "interpretation": interpretation,
        "flags": flags,
    }


# ============================================================
# PEG 계산 (단일)
# ============================================================
def _calculate_peg(per: Optional[float], growth_rate: Optional[float],
                   label: str = "") -> dict:
    """
    PEG = PER / 성장률(%)

    Returns:
        {
            "value":       PEG 값 또는 None,
            "verdict":     ✓✓ / ✓ / △ / ⚠ / ✗ / N/A,
            "growth_used": 사용한 성장률 (raw, 예: 0.45),
            "note":        설명 (왜 N/A인지 등),
            "label":       어떤 PEG 변형인지,
        }
    """
    if per is None:
        return {"value": None, "verdict": "N/A", "growth_used": growth_rate,
                "note": "PER 계산 불가 (가격 또는 EPS 누락)", "label": label}
    if per < 0:
        return {"value": None, "verdict": "N/A", "growth_used": growth_rate,
                "note": "PER 음수 (적자) - PEG 의미 없음", "label": label}
    if growth_rate is None:
        return {"value": None, "verdict": "N/A", "growth_used": None,
                "note": "성장률 데이터 누락", "label": label}
    if growth_rate <= 0:
        return {"value": None, "verdict": "N/A", "growth_used": growth_rate,
                "note": "EPS 역성장 - PEG 계산 불가", "label": label}
    if growth_rate < PEG_TRAP_RULES["min_growth_for_peg"]:
        # 5% 미만 — 계산은 하지만 의미 약함
        peg = per / (growth_rate * 100)
        return {"value": peg, "verdict": "⚠",
                "growth_used": growth_rate,
                "note": f"성장률 {growth_rate:.1%} 매우 낮음 - PEG 의미 약함",
                "label": label}

    # 정상 계산
    peg_value = per / (growth_rate * 100)
    verdict = _peg_verdict(peg_value)

    return {"value": peg_value, "verdict": verdict,
            "growth_used": growth_rate, "note": "OK", "label": label}


def _peg_verdict(peg: float) -> str:
    """PEG 판정 (✓✓ / ✓ / △ / ⚠ / ✗)"""
    if peg < PEG_THRESHOLDS["very_attractive"]:
        return "✓✓"
    if peg < PEG_THRESHOLDS["attractive"]:
        return "✓"
    if peg < PEG_THRESHOLDS["neutral"]:
        return "△"
    if peg < PEG_THRESHOLDS["expensive"]:
        return "⚠"
    return "✗"


# ============================================================
# Trap Detection
# ============================================================
def _detect_traps(
    peg_ttm: dict, peg_fwd_1y: dict, peg_fwd_2y: dict,
    growth_fwd_2y: Optional[float],
    growth_result: Optional[dict],
    sector_internal: Optional[str],
    operating_margin_current: Optional[float],
    operating_margin_historical_max: Optional[float],
) -> list:
    """
    ★ PDF 핵심 ★ — PEG가 좋아 보여도 함정인지 검증.

    Returns:
        flag dict 리스트 (각 flag = {type, severity, msg})
    """
    flags = []

    # Trap 1: 성장률이 비현실적으로 높음
    if growth_fwd_2y is not None and growth_fwd_2y > PEG_TRAP_RULES["growth_too_high"]:
        flags.append({
            "type": "growth_too_high",
            "severity": "warning",
            "msg": (f"향후 2년 EPS 성장률 컨센서스 {growth_fwd_2y:.0%} - "
                    f"매우 높은 추정치, 달성 가능성 검토 필요"),
        })

    # Trap 2: 매출-EPS 갭 과도 (growth_result 참조)
    if growth_result is not None:
        gap_decomp = growth_result.get("metrics", {}).get("gap_decomposition", {})
        gap_pct = gap_decomp.get("gap_pct")
        if gap_pct is not None and gap_pct > PEG_TRAP_RULES["revenue_eps_gap"]:
            driver = gap_decomp.get("primary_driver", "")
            flags.append({
                "type": "revenue_eps_gap",
                "severity": "warning",
                "msg": (f"EPS 성장이 매출 성장보다 {gap_pct:.1%}p 초과 — {driver} "
                        f"→ 일회성 효과 가능성, PEG 분모 변동 위험"),
            })

        # Trap 4: 자사주 매입 효과 과도 (share_contribution 참조)
        share_contrib = gap_decomp.get("share_contribution")
        if share_contrib is not None and share_contrib > PEG_TRAP_RULES["buyback_contribution"]:
            flags.append({
                "type": "buyback_contribution_high",
                "severity": "info",
                "msg": (f"EPS 성장의 {share_contrib:.0%}가 자사주 매입 효과 "
                        f"- 실질 영업 성장 별도 검토 필요"),
            })

    # Trap 5: 사이클 정점 (반도체/소재/철강) + 마진 사상 최고
    cyclical_sectors = {"TECH_AI_INFRA", "SEMICONDUCTOR_MEM", "INDUSTRIAL_HEAVY"}
    if sector_internal in cyclical_sectors:
        if (operating_margin_current is not None
                and operating_margin_historical_max is not None):
            # 현재 마진이 역사적 최고의 95% 이상이면 사이클 정점 가능성
            if operating_margin_current >= operating_margin_historical_max * 0.95:
                flags.append({
                    "type": "cycle_peak",
                    "severity": "warning",
                    "msg": (f"사이클 산업이고 영업이익률({operating_margin_current:.1%})이 "
                            f"역사적 최고({operating_margin_historical_max:.1%}) 근처 "
                            f"- 사이클 정점 가능성, 향후 정상화 시 PEG 분모 악화 위험"),
                })

    # PEG 자체에 ✗가 있으면 경고
    for peg in [peg_ttm, peg_fwd_1y, peg_fwd_2y]:
        if peg.get("verdict") == "✗":
            flags.append({
                "type": "peg_expensive",
                "severity": "warning",
                "msg": f"{peg.get('label', 'PEG')} = {peg['value']:.2f} - 성장 대비 명백히 고평가",
            })

    return flags


# ============================================================
# 헬퍼: EPS, 마진 추출
# ============================================================
def _get_ttm_eps(income_q: pd.DataFrame, info: dict) -> Optional[float]:
    """
    TTM EPS 계산. 분기 4개 합산 우선, 없으면 yfinance trailingEps.
    """
    # 분기 Diluted EPS 4개 합
    eps_ttm = ttm_sum(income_q, "diluted_eps", INCOME_ROW_ALIASES)
    if eps_ttm is None:
        eps_ttm = ttm_sum(income_q, "basic_eps", INCOME_ROW_ALIASES)

    # Fallback: yfinance.info
    if eps_ttm is None:
        eps_ttm = info.get("trailingEps")

    if eps_ttm is not None and not _is_valid_number(eps_ttm):
        eps_ttm = None

    return eps_ttm


def _calculate_eps_cagr_past(income_a: pd.DataFrame, years: int = 2) -> Optional[float]:
    """과거 N년 EPS CAGR (Diluted EPS 우선)."""
    if income_a is None or income_a.empty:
        return None

    aliases = INCOME_ROW_ALIASES.get("diluted_eps", [])
    series = get_row_series(income_a, aliases).dropna()
    if len(series) <= years:
        aliases = INCOME_ROW_ALIASES.get("basic_eps", [])
        series = get_row_series(income_a, aliases).dropna()

    if len(series) <= years:
        return None

    end_value = series.iloc[0]
    start_value = series.iloc[years]
    return safe_cagr(end_value, start_value, years)


def _get_current_operating_margin(income_q: pd.DataFrame) -> Optional[float]:
    """현재 TTM 영업이익률."""
    rev = ttm_sum(income_q, "revenue", INCOME_ROW_ALIASES)
    op = ttm_sum(income_q, "operating_income", INCOME_ROW_ALIASES)
    return safe_divide(op, rev)


def _get_historical_max_operating_margin(income_a: pd.DataFrame) -> Optional[float]:
    """연간 영업이익률 5년 이력 중 최고치."""
    if income_a is None or income_a.empty:
        return None
    rev_series = get_row_series(income_a, INCOME_ROW_ALIASES["revenue"])
    op_series = get_row_series(income_a, INCOME_ROW_ALIASES["operating_income"])

    if rev_series.empty or op_series.empty:
        return None

    margins = []
    common = sorted(set(rev_series.index) & set(op_series.index), reverse=True)[:5]
    for col in common:
        try:
            r = float(rev_series[col])
            o = float(op_series[col])
            if r > 0:
                margins.append(o / r)
        except (TypeError, ValueError):
            continue
    return max(margins) if margins else None


def _is_valid_number(x) -> bool:
    if x is None:
        return False
    try:
        return not pd.isna(x) and isinstance(float(x), float)
    except (TypeError, ValueError):
        return False


# ============================================================
# 해석 문자열 생성
# ============================================================
def _build_interpretation(
    per_ttm, forward_per_2y,
    peg_ttm, peg_forward_1y, peg_forward_2y,
    pbr, psr, ev_ebitda,
    roe_above_coe, roe, coe,
    n_traps,
) -> str:
    lines = []

    # 기본 멀티플
    parts = []
    if per_ttm is not None:
        parts.append(f"PER(TTM) {per_ttm:.1f}배")
    if forward_per_2y is not None:
        parts.append(f"Forward PER(2Y) {forward_per_2y:.1f}배")
    if pbr is not None:
        parts.append(f"PBR {pbr:.2f}배")
    if parts:
        lines.append(", ".join(parts) + ".")

    # 메인 PEG (Forward 2Y)
    main = peg_forward_2y
    if main.get("value") is not None:
        lines.append(
            f"메인 시그널: PEG(Forward 2Y) {main['value']:.2f} {main['verdict']}"
            f" — 성장률 {main['growth_used']:.1%} 대입."
        )
        if main["verdict"] in ("✓", "✓✓"):
            lines.append("성장 대비 매력적 구간.")
        elif main["verdict"] == "✗":
            lines.append("성장 대비 명백히 고평가 구간.")
    else:
        # Forward 2Y가 안 되면 TTM이라도
        if peg_ttm.get("value") is not None:
            lines.append(
                f"PEG(Forward 2Y) 계산 불가 — TTM 기준 {peg_ttm['value']:.2f} {peg_ttm['verdict']}"
                f" 사용. (Note: {main['note']})"
            )
        else:
            lines.append(f"PEG 계산 불가: {main['note']}")

    # ROE > COE
    if roe_above_coe is True:
        lines.append(f"ROE {roe:.1%} > 자기자본비용 {coe:.0%} → 가치 창출 ✓")
    elif roe_above_coe is False:
        lines.append(f"ROE {roe:.1%} < 자기자본비용 {coe:.0%} → 가치 파괴 위험 ⚠")

    # Trap 요약
    if n_traps > 0:
        lines.append(f"⚠ {n_traps}개 함정 신호 감지 - 상세는 flags 참조.")

    return " ".join(lines) if lines else "밸류에이션 분석에 필요한 데이터가 부족합니다."
