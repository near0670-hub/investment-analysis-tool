"""
modules/valuation_timeseries.py — Phase 3: Valuation 시계열 분석

PER, PBR, 배당수익률을 시계열로 분석:
- 과거 4년 actual + 미래 1년 컨센서스
- 5Y 평균 계산
- 자동 해설 + 시그널 분류 (Re-rating, Premium, Value trap 등)

데이터 소스:
- 한국 종목: 네이버 (PER Naver, PBR Naver, Dividend Yield 직접 시계열 제공)
- 미국 종목: yfinance info (현재 시점만, 시계열은 Phase 3.5에서 역산)

자동 해설 임계값 (모두 코드에 투명하게 노출):
- 할인 (discount): current < 5Y avg × 0.85 (-15%)
- 프리미엄 (premium): current > 5Y avg × 1.20 (+20%)
- Re-rating opportunity: PER < avg × 0.85 + consensus growth > 15%
- Value trap warning: PER < avg × 0.85 + revenue YoY < -10%
- Cyclical peak risk: PER < 5Y min + operating margin > peak × 0.95
- Mean reversion: |current - avg| < avg × 0.10
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

# ============================================================
# 임계값 (투명하게 노출 — 사용자가 검증 가능하도록)
# ============================================================
THRESHOLDS = {
    "discount_factor": 0.85,         # 5Y avg × 0.85 = -15% 이하
    "premium_factor": 1.20,          # 5Y avg × 1.20 = +20% 이상
    "rerating_growth_min": 0.15,     # Re-rating은 컨센서스 growth > 15%
    "value_trap_revenue_min": -0.10, # Value trap은 매출 YoY < -10%
    "mean_reversion_band": 0.10,     # 평균에서 ±10% 이내면 mean reversion
    "cyclical_peak_margin": 0.95,    # 마진이 historical peak × 0.95 이상
}


# ============================================================
# 메인 함수
# ============================================================
def calculate_valuation_timeseries(data: dict, n_history: int = 4) -> Optional[dict]:
    """
    Valuation 시계열 + 자동 해설 계산.

    Args:
        data: data_loader.load_company_data() 결과
        n_history: 과거 연도 개수 (기본 4년) → +1년 컨센서스 = 5개 기간

    Returns:
        성공 시 dict, 실패 시 None
    """
    country = data.get("meta", {}).get("country", "US")

    if country == "KR":
        return _calculate_valuation_kr(data, n_history)
    else:
        return _calculate_valuation_us(data, n_history)


# ============================================================
# 한국 종목: 네이버 PER/PBR/배당수익률 시계열
# ============================================================
def _calculate_valuation_kr(data: dict, n_history: int) -> Optional[dict]:
    """한국 종목 valuation 시계열. 네이버에서 직접."""
    naver_data = data.get("kr_naver_consensus")
    if naver_data is None:
        return None

    naver_annual = naver_data.get("annual", pd.DataFrame())
    if naver_annual.empty:
        return None

    # 네이버 연간 컬럼 (Timestamp) - 최근 n_history + 1
    naver_cols = sorted(naver_annual.columns)
    if len(naver_cols) < 2:
        return None

    selected_cols = naver_cols[-(n_history + 1):]

    # 각 기간별 valuation 메트릭 추출
    rows = []
    for col in selected_cols:
        period_label = _format_year(col)
        is_consensus = _is_consensus_period(naver_data, col)

        per = _safe_at(naver_annual, "PER Naver", col)
        pbr = _safe_at(naver_annual, "PBR Naver", col)
        div_yield = _safe_at(naver_annual, "Dividend Yield", col)  # % 단위
        # EV/EBITDA는 네이버에 없음. None으로 둠.

        rows.append({
            "period": period_label,
            "is_consensus": is_consensus,
            "per": per,
            "pbr": pbr,
            "dividend_yield": div_yield / 100 if div_yield is not None else None,  # 0~1 비율로
            "ev_ebitda": None,
        })

    if len(rows) < 2:
        return None

    df = pd.DataFrame(rows)

    # 5Y 평균 (actual만 사용, 컨센서스 제외)
    actual_df = df[df["is_consensus"] == False]

    avg_metrics = {
        "per_avg": actual_df["per"].mean() if len(actual_df) > 0 else None,
        "per_min": actual_df["per"].min() if len(actual_df) > 0 else None,
        "per_max": actual_df["per"].max() if len(actual_df) > 0 else None,
        "pbr_avg": actual_df["pbr"].mean() if len(actual_df) > 0 else None,
        "pbr_min": actual_df["pbr"].min() if len(actual_df) > 0 else None,
        "pbr_max": actual_df["pbr"].max() if len(actual_df) > 0 else None,
        "div_yield_avg": actual_df["dividend_yield"].mean() if len(actual_df) > 0 else None,
    }

    # 현재 값 = 마지막 actual (오늘 시점 valuation)
    current = actual_df.iloc[-1] if len(actual_df) > 0 else None
    consensus_row = df[df["is_consensus"] == True].iloc[0] if (df["is_consensus"] == True).any() else None

    # 자동 해설 생성
    narrative_data = _generate_valuation_narrative(
        df=df,
        avg_metrics=avg_metrics,
        current=current,
        consensus_row=consensus_row,
        data=data,
    )

    return {
        "components": df,
        "avg_metrics": avg_metrics,
        "current": current.to_dict() if current is not None else None,
        "consensus": consensus_row.to_dict() if consensus_row is not None else None,
        "narrative": narrative_data["narrative"],
        "signals": narrative_data["signals"],
        "evidence": narrative_data["evidence"],
        "source_note": "Source: Naver Securities · K-IFRS · "
                       "PER/PBR/Dividend Yield from annual consensus data",
        "country": "KR",
        "thresholds": THRESHOLDS,
    }


# ============================================================
# 미국 종목: yfinance (현재 시점만, 시계열은 Phase 3.5)
# ============================================================
def _calculate_valuation_us(data: dict, n_history: int) -> Optional[dict]:
    """미국 종목 valuation. 현재 시점 + forward 1Y만."""
    info = data.get("info", {})
    if not info:
        return None

    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    pbr = info.get("priceToBook")
    div_yield = info.get("dividendYield")  # yfinance는 0~1 비율로 줌
    ev_ebitda = info.get("enterpriseToEbitda")

    if all(v is None for v in [trailing_pe, forward_pe, pbr, ev_ebitda]):
        return None

    # 현재 1개 기간 + 컨센서스 1개 = 최소 표시
    rows = [{
        "period": "TTM",
        "is_consensus": False,
        "per": trailing_pe,
        "pbr": pbr,
        "dividend_yield": div_yield,
        "ev_ebitda": ev_ebitda,
    }]

    if forward_pe is not None:
        rows.append({
            "period": "FY+1 (E)",
            "is_consensus": True,
            "per": forward_pe,
            "pbr": None,    # forward PBR는 yfinance에 없음
            "dividend_yield": None,
            "ev_ebitda": None,
        })

    df = pd.DataFrame(rows)

    avg_metrics = {
        "per_avg": trailing_pe,    # TTM만 → 평균은 의미 없음
        "per_min": None,
        "per_max": None,
        "pbr_avg": pbr,
        "pbr_min": None,
        "pbr_max": None,
        "div_yield_avg": div_yield,
    }

    current = pd.Series(rows[0])
    consensus_row = pd.Series(rows[1]) if len(rows) > 1 else None

    # 자동 해설 (제한적 — 시계열 없으니 평균 비교 못 함)
    narrative_data = _generate_valuation_narrative_us(
        df=df, current=current, consensus_row=consensus_row, data=data
    )

    return {
        "components": df,
        "avg_metrics": avg_metrics,
        "current": current.to_dict(),
        "consensus": consensus_row.to_dict() if consensus_row is not None else None,
        "narrative": narrative_data["narrative"],
        "signals": narrative_data["signals"],
        "evidence": narrative_data["evidence"],
        "source_note": "Source: yfinance · US-GAAP · "
                       "TTM + Forward only (full time series in Phase 3.5)",
        "country": "US",
        "thresholds": THRESHOLDS,
    }


# ============================================================
# 자동 해설 생성 (한국 종목 — 5Y 평균 비교 가능)
# ============================================================
def _generate_valuation_narrative(
    df: pd.DataFrame,
    avg_metrics: dict,
    current,
    consensus_row,
    data: dict,
) -> dict:
    """
    한국 종목 valuation 해설 + 시그널 분류.

    시그널 우선순위 (높은 것부터 적용):
    1. Value Trap Warning (가장 위험)
    2. Cyclical Peak Risk (사이클 위험)
    3. Re-rating Opportunity (가장 매력)
    4. Premium Territory (조심)
    5. Mean Reversion (보통)
    6. Discount (저평가)
    """
    signals = []
    evidence = []  # 근거 숫자 리스트

    if current is None or avg_metrics["per_avg"] is None:
        return {
            "narrative": "Insufficient data for valuation analysis.",
            "signals": [],
            "evidence": [],
        }

    current_per = current.get("per")
    avg_per = avg_metrics["per_avg"]
    min_per = avg_metrics["per_min"]

    if current_per is None or avg_per is None:
        return {
            "narrative": "Current PER not available.",
            "signals": [],
            "evidence": [],
        }

    # PER 평균 대비 변화
    per_vs_avg = (current_per / avg_per) - 1.0  # 음수 = 평균보다 낮음

    # 매출/이익 증가율 (Trap Detection / Re-rating 판정용)
    revenue_yoy = _get_recent_revenue_yoy(data)
    consensus_eps_growth = _get_consensus_growth(consensus_row, current)

    # 마진 (Cyclical Peak 판정용)
    op_margin_current = _get_operating_margin_current(data)
    op_margin_peak = _get_operating_margin_peak(data)

    # ====================
    # 시그널 분류 (if/elif 순서대로 — 가장 먼저 매칭되는 게 메인)
    # ====================

    # 1. Value Trap Warning
    if (current_per < avg_per * THRESHOLDS["discount_factor"]
        and revenue_yoy is not None
        and revenue_yoy < THRESHOLDS["value_trap_revenue_min"]):
        signals.append({
            "label": "VALUE TRAP WARNING",
            "variant": "negative",
            "description": "Cheap PER but earnings deteriorating",
        })
        evidence.append(f"Current PER {current_per:.1f}x < 5Y avg {avg_per:.1f}x × 0.85 = {avg_per * 0.85:.1f}x")
        evidence.append(f"Revenue YoY {revenue_yoy*100:+.1f}% < threshold {THRESHOLDS['value_trap_revenue_min']*100:.0f}%")

    # 2. Cyclical Peak Risk
    elif (min_per is not None and current_per < min_per * 1.15  # PER 5Y 최저에 근접
          and op_margin_current is not None and op_margin_peak is not None
          and op_margin_current > op_margin_peak * THRESHOLDS["cyclical_peak_margin"]):
        signals.append({
            "label": "CYCLICAL PEAK RISK",
            "variant": "warning",
            "description": "Cheap PER + margin near peak — normalization risk",
        })
        evidence.append(f"Current PER {current_per:.1f}x near 5Y min {min_per:.1f}x")
        evidence.append(f"Operating margin {op_margin_current*100:.1f}% at {op_margin_current/op_margin_peak*100:.0f}% of historical peak {op_margin_peak*100:.1f}%")

    # 3. Re-rating Opportunity (최고 시그널)
    elif (current_per < avg_per * THRESHOLDS["discount_factor"]
          and consensus_eps_growth is not None
          and consensus_eps_growth > THRESHOLDS["rerating_growth_min"]):
        signals.append({
            "label": "RE-RATING OPPORTUNITY",
            "variant": "positive",
            "description": "Trading at discount + strong consensus growth",
        })
        evidence.append(f"Current PER {current_per:.1f}x = {per_vs_avg*100:+.1f}% vs 5Y avg {avg_per:.1f}x")
        evidence.append(f"Consensus EPS growth: {consensus_eps_growth*100:+.1f}% (> threshold {THRESHOLDS['rerating_growth_min']*100:.0f}%)")

    # 4. Premium Territory
    elif current_per > avg_per * THRESHOLDS["premium_factor"]:
        signals.append({
            "label": "PREMIUM TERRITORY",
            "variant": "warning",
            "description": "Trading well above historical average",
        })
        evidence.append(f"Current PER {current_per:.1f}x = {per_vs_avg*100:+.1f}% vs 5Y avg {avg_per:.1f}x")
        evidence.append(f"Threshold: > +{(THRESHOLDS['premium_factor']-1)*100:.0f}% premium")

    # 5. Discount
    elif current_per < avg_per * THRESHOLDS["discount_factor"]:
        signals.append({
            "label": "DISCOUNT",
            "variant": "positive",
            "description": "Trading below historical average",
        })
        evidence.append(f"Current PER {current_per:.1f}x = {per_vs_avg*100:+.1f}% vs 5Y avg {avg_per:.1f}x")
        evidence.append(f"Threshold: < -{(1-THRESHOLDS['discount_factor'])*100:.0f}% discount")

    # 6. Mean Reversion (Default)
    elif abs(per_vs_avg) < THRESHOLDS["mean_reversion_band"]:
        signals.append({
            "label": "NEAR MEAN",
            "variant": "neutral",
            "description": "Trading close to historical average",
        })
        evidence.append(f"Current PER {current_per:.1f}x ≈ 5Y avg {avg_per:.1f}x ({per_vs_avg*100:+.1f}%)")
    else:
        # 평균과 비교해서 ±10~20% 사이 — 명확 시그널 없음
        direction = "above" if per_vs_avg > 0 else "below"
        signals.append({
            "label": "MIXED",
            "variant": "neutral",
            "description": f"Trading moderately {direction} historical average",
        })
        evidence.append(f"Current PER {current_per:.1f}x = {per_vs_avg*100:+.1f}% vs 5Y avg {avg_per:.1f}x")

    # 메인 narrative 문장 조립
    primary_signal = signals[0]
    narrative_parts = []

    narrative_parts.append(
        f"Current PER {current_per:.1f}x vs 5Y avg {avg_per:.1f}x → {per_vs_avg*100:+.1f}% deviation"
    )

    if consensus_row is not None and consensus_row.get("per") is not None:
        c_per = consensus_row["per"]
        narrative_parts.append(f"FY+1 (E) PER {c_per:.1f}x")

    narrative_parts.append(primary_signal["description"])

    narrative = ". ".join(narrative_parts) + "."

    return {
        "narrative": narrative,
        "signals": signals,
        "evidence": evidence,
    }


# ============================================================
# 자동 해설 (미국 종목 — 시계열 없으니 제한적)
# ============================================================
def _generate_valuation_narrative_us(df, current, consensus_row, data):
    """미국 종목은 시계열 없어서 단순 해설만."""
    signals = []
    evidence = []

    trailing = current.get("per")
    forward = consensus_row.get("per") if consensus_row is not None else None

    if trailing is None:
        return {"narrative": "PER not available.", "signals": [], "evidence": []}

    parts = []
    parts.append(f"Trailing PER {trailing:.1f}x")

    if forward is not None:
        delta = (forward / trailing) - 1
        parts.append(f"Forward PER {forward:.1f}x ({delta*100:+.1f}% vs TTM)")

        # 시그널: forward가 trailing보다 낮으면 → EPS 성장 예상
        if delta < -0.15:
            signals.append({
                "label": "EPS GROWTH EXPECTED",
                "variant": "positive",
                "description": "Forward PER significantly lower → consensus expects EPS growth",
            })
            evidence.append(f"Forward {forward:.1f}x / Trailing {trailing:.1f}x = {delta*100:+.1f}%")
        elif delta > 0.15:
            signals.append({
                "label": "EPS DECLINE EXPECTED",
                "variant": "warning",
                "description": "Forward PER higher than TTM → consensus expects EPS decline",
            })
            evidence.append(f"Forward {forward:.1f}x / Trailing {trailing:.1f}x = {delta*100:+.1f}%")

    if not signals:
        signals.append({
            "label": "STANDARD",
            "variant": "neutral",
            "description": "Time series analysis unavailable for US equities (Phase 3.5)",
        })

    return {
        "narrative": ". ".join(parts) + ".",
        "signals": signals,
        "evidence": evidence,
    }


# ============================================================
# 보조 함수: 데이터 추출
# ============================================================
def _get_recent_revenue_yoy(data: dict) -> Optional[float]:
    """최근 분기 매출 YoY (Value Trap 판정용)."""
    naver_data = data.get("kr_naver_consensus")
    if naver_data is None:
        return None

    naver_q = naver_data.get("quarterly", pd.DataFrame())
    if naver_q.empty or "Total Revenue" not in naver_q.index:
        return None

    # 최근 분기 + 4분기 전 비교
    cols = sorted(naver_q.columns)
    if len(cols) < 5:
        return None

    try:
        recent = float(naver_q.at["Total Revenue", cols[-1]])
        yoy = float(naver_q.at["Total Revenue", cols[-5]])
        if yoy == 0:
            return None
        return (recent - yoy) / abs(yoy)
    except (KeyError, TypeError, ValueError):
        return None


def _get_consensus_growth(consensus_row, current) -> Optional[float]:
    """컨센서스 PER이 현재보다 낮으면 → EPS 성장 의미. PER에서 역산."""
    if consensus_row is None or current is None:
        return None
    c_per = consensus_row.get("per")
    cur_per = current.get("per")
    if c_per is None or cur_per is None or c_per <= 0 or cur_per <= 0:
        return None
    # 가격이 변하지 않는다고 가정하면:
    # Forward PER = Price / Forward EPS, Trailing PER = Price / Trailing EPS
    # → Forward EPS / Trailing EPS = Trailing PER / Forward PER
    # → growth = (Trailing PER / Forward PER) - 1
    return (cur_per / c_per) - 1


def _get_operating_margin_current(data: dict) -> Optional[float]:
    """최근 분기 영업이익률."""
    income_quarterly = data.get("income_quarterly", pd.DataFrame())
    if income_quarterly.empty:
        return None

    from modules.financial_metrics import INCOME_ROW_ALIASES, get_row_series
    op_income = get_row_series(income_quarterly, INCOME_ROW_ALIASES.get("operating_income", ["Operating Income"]))
    revenue = get_row_series(income_quarterly, INCOME_ROW_ALIASES["revenue"])

    if op_income.empty or revenue.empty:
        return None

    try:
        recent_op = float(op_income.dropna().iloc[-1])
        recent_rev = float(revenue.dropna().iloc[-1])
        if recent_rev == 0:
            return None
        return recent_op / recent_rev
    except (IndexError, ValueError, TypeError):
        return None


def _get_operating_margin_peak(data: dict) -> Optional[float]:
    """역대 최고 영업이익률 (분기 기준)."""
    income_quarterly = data.get("income_quarterly", pd.DataFrame())
    if income_quarterly.empty:
        return None

    from modules.financial_metrics import INCOME_ROW_ALIASES, get_row_series
    op_income = get_row_series(income_quarterly, INCOME_ROW_ALIASES.get("operating_income", ["Operating Income"]))
    revenue = get_row_series(income_quarterly, INCOME_ROW_ALIASES["revenue"])

    if op_income.empty or revenue.empty:
        return None

    try:
        margins = (op_income / revenue).dropna()
        if len(margins) == 0:
            return None
        return float(margins.max())
    except (ValueError, TypeError, ZeroDivisionError):
        return None


# ============================================================
# 작은 헬퍼
# ============================================================
def _safe_at(df: pd.DataFrame, row_name: str, col) -> Optional[float]:
    if df is None or df.empty or row_name not in df.index:
        return None
    try:
        val = df.at[row_name, col]
        if pd.isna(val):
            return None
        return float(val)
    except (KeyError, ValueError, TypeError):
        return None


def _format_year(col) -> str:
    try:
        ts = pd.Timestamp(col)
        return f"FY{ts.year % 100:02d}"
    except (TypeError, ValueError):
        return str(col)


def _is_consensus_period(naver_data: dict, col) -> bool:
    if naver_data is None:
        return False
    future_periods = naver_data.get("future_periods", [])
    try:
        year = pd.Timestamp(col).year
        import re
        for fp in future_periods:
            m = re.match(r"^(\d{4})", fp)
            if m and int(m.group(1)) == year:
                return True
    except (TypeError, ValueError):
        pass
    return False
