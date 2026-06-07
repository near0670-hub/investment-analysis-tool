"""
modules/stability_analysis.py — Phase 4: Stability (재무 안정성) 분석

CFA 표준 안정성 지표 + 종합 시그널.

지표:
    Solvency (장기 안정성):
        - debt_ratio           = Total Debt / Total Assets
        - equity_ratio         = Stockholders Equity / Total Assets
        - debt_to_equity       = Total Debt / Stockholders Equity
        - net_debt_to_ebitda   = (Total Debt - Cash) / EBITDA (TTM)

    Liquidity (단기 유동성):
        - current_ratio        = Current Assets / Current Liabilities
        - quick_ratio          = (Current Assets - Inventory) / Current Liabilities
        - cash_ratio           = Cash / Current Liabilities

    Coverage (이자 부담):
        - interest_coverage    = EBIT / Interest Expense (TTM)

    Composite:
        - altman_z             = 1.2 A + 1.4 B + 3.3 C + 0.6 D + 1.0 E

시그널 4단계 (PROFITABILITY 모듈과 동일한 dict 출력 스키마):
    STABLE    — 모든 항목 정상
    ADEQUATE  — 1~2개 watch
    STRESSED  — 다수 watch / 1개 warning
    DISTRESS  — 다수 warning / 이자 미충당

데이터 출처:
    yfinance balance_sheet + income_statement (quarterly, TTM)
    DART → dart_source가 이미 yfinance 영문 라벨로 정규화하므로 동일 alias 사용 가능
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# ============================================================
# Self-contained 헬퍼 (financial_metrics 의존 없이 단독 동작)
# 다른 모듈과의 결합도 0 — 본인 financial_metrics.py 구조와 무관
# ============================================================

# 빈 dict — 로컬 alias만 사용 (LOCAL_BALANCE_ALIASES, LOCAL_INCOME_ALIASES)
BALANCE_ROW_ALIASES: dict = {}
INCOME_ROW_ALIASES: dict = {}


def get_row_series(df: pd.DataFrame, aliases) -> pd.Series:
    """
    DataFrame index에서 aliases 중 하나라도 매칭되는 행의 시계열 반환.

    yfinance/DART 모두: index=항목명, columns=날짜(최신=좌측 iloc[:, 0]).
    매칭 실패 시 빈 Series 반환 (None 아님 → 호출부 .empty 체크).
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)
    for alias in aliases:
        if alias in df.index:
            s = df.loc[alias]
            # 동일 라벨이 중복된 경우 첫 번째 행 사용
            if isinstance(s, pd.DataFrame):
                s = s.iloc[0]
            return s.dropna()
    return pd.Series(dtype=float)


def ttm_sum(series: pd.Series) -> Optional[float]:
    """최근 4분기 합계. 4개 미만이면 None."""
    if series is None or series.empty:
        return None
    s = series.dropna()
    if len(s) < 4:
        return None
    return float(s.iloc[:4].sum())


def safe_div(a, b) -> Optional[float]:
    """0/None 안전 나눗셈."""
    if a is None or b is None:
        return None
    try:
        b = float(b)
        if abs(b) < 1e-12:
            return None
        return float(a) / b
    except (ValueError, TypeError):
        return None


# ============================================================
# 추가 alias (financial_metrics.py에 아직 없을 가능성 있는 키 보강)
# ============================================================
# 모듈 로컬 alias — financial_metrics.BALANCE_ROW_ALIASES 키에 없으면 fallback
LOCAL_BALANCE_ALIASES = {
    "total_assets": [
        "Total Assets",
    ],
    "total_liabilities": [
        "Total Liabilities Net Minority Interest",
        "Total Liab",
        "Total Liabilities",
    ],
    "total_debt": [
        "Total Debt",
        "Net Debt",  # yfinance 일부 케이스
    ],
    "long_term_debt": [
        "Long Term Debt",
        "Long Term Debt And Capital Lease Obligation",
    ],
    "short_term_debt": [
        "Current Debt",
        "Short Long Term Debt",
        "Current Debt And Capital Lease Obligation",
    ],
    "current_assets": [
        "Current Assets",
        "Total Current Assets",
    ],
    "current_liabilities": [
        "Current Liabilities",
        "Total Current Liabilities",
    ],
    "inventory": [
        "Inventory",
    ],
    "cash": [
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
        "Cash",
    ],
    "stockholders_equity": [
        "Stockholders Equity",
        "Total Stockholder Equity",
        "Common Stock Equity",
    ],
    "retained_earnings": [
        "Retained Earnings",
    ],
    "working_capital": [
        "Working Capital",
    ],
}

LOCAL_INCOME_ALIASES = {
    "operating_income": [
        "Operating Income",
        "Operating Income Or Loss",
        "Ebit",
        "EBIT",
    ],
    "interest_expense": [
        "Interest Expense",
        "Interest Expense Non Operating",
    ],
    "ebitda": [
        "Normalized EBITDA",
        "EBITDA",
        "Ebitda",
    ],
    "depreciation": [
        "Reconciled Depreciation",
        "Depreciation And Amortization",
        "Depreciation Amortization Depletion",
    ],
    "revenue": [
        "Total Revenue",
        "Operating Revenue",
    ],
}


def _aliases(key: str, src: str = "balance") -> list[str]:
    """financial_metrics 글로벌 alias가 있으면 우선, 없으면 로컬 사용."""
    if src == "balance":
        global_map = BALANCE_ROW_ALIASES if isinstance(BALANCE_ROW_ALIASES, dict) else {}
        local_map = LOCAL_BALANCE_ALIASES
    else:
        global_map = INCOME_ROW_ALIASES if isinstance(INCOME_ROW_ALIASES, dict) else {}
        local_map = LOCAL_INCOME_ALIASES
    return global_map.get(key) or local_map.get(key, [])


# ============================================================
# 지표 추출 헬퍼
# ============================================================
def _latest(df: pd.DataFrame, key: str, src: str = "balance") -> Optional[float]:
    """가장 최근 분기/연도의 값. None 시 추출 실패."""
    if df is None or df.empty:
        return None
    series = get_row_series(df, _aliases(key, src=src))
    if series is None or series.empty:
        return None
    # 모듈 컨벤션: yfinance/DART 모두 최신이 iloc[0]
    val = series.dropna()
    return float(val.iloc[0]) if not val.empty else None


def _ttm(income_q: pd.DataFrame, key: str) -> Optional[float]:
    """TTM 합산 (최근 4분기)."""
    if income_q is None or income_q.empty:
        return None
    series = get_row_series(income_q, _aliases(key, src="income"))
    if series is None or series.empty:
        return None
    return ttm_sum(series)


def _compose_total_debt(balance_q: pd.DataFrame) -> Optional[float]:
    """
    Total Debt 직접값 없으면 단기차입금 + 장기차입금으로 합성.
    """
    direct = _latest(balance_q, "total_debt")
    if direct is not None:
        return direct
    short = _latest(balance_q, "short_term_debt") or 0.0
    long_ = _latest(balance_q, "long_term_debt") or 0.0
    composed = short + long_
    return composed if composed > 0 else None


def _compose_ebitda(income_q: pd.DataFrame, cashflow_q: pd.DataFrame) -> Optional[float]:
    """
    EBITDA 직접값 없으면 Operating Income + Depreciation으로 합성.
    Cash flow에서 D&A 가져오는 게 더 정확 (income에서 항상 잡히지 않음).
    """
    direct = _ttm(income_q, "ebitda")
    if direct is not None:
        return direct
    op = _ttm(income_q, "operating_income")
    if op is None:
        return None
    # D&A: income 우선, 없으면 cashflow
    da = _ttm(income_q, "depreciation")
    if da is None and cashflow_q is not None and not cashflow_q.empty:
        for k in ["Depreciation And Amortization", "Depreciation",
                  "Depreciation Amortization Depletion"]:
            s = get_row_series(cashflow_q, [k])
            if s is not None and not s.empty:
                da = ttm_sum(s)
                break
    return op + (da or 0.0)


# ============================================================
# Altman Z-Score (Public Manufacturing 원형)
#   Z = 1.2 A + 1.4 B + 3.3 C + 0.6 D + 1.0 E
#   A = Working Capital / Total Assets
#   B = Retained Earnings / Total Assets
#   C = EBIT / Total Assets
#   D = Market Cap / Total Liabilities
#   E = Revenue / Total Assets
# ============================================================
def _altman_z(
    *,
    total_assets: Optional[float],
    current_assets: Optional[float],
    current_liabilities: Optional[float],
    retained_earnings: Optional[float],
    ebit_ttm: Optional[float],
    market_cap: Optional[float],
    total_liabilities: Optional[float],
    revenue_ttm: Optional[float],
) -> Optional[float]:
    if not total_assets or total_assets <= 0:
        return None

    # Working Capital = CA - CL (없으면 None)
    wc = None
    if current_assets is not None and current_liabilities is not None:
        wc = current_assets - current_liabilities

    a = safe_div(wc, total_assets) if wc is not None else None
    b = safe_div(retained_earnings, total_assets)
    c = safe_div(ebit_ttm, total_assets)
    d = safe_div(market_cap, total_liabilities) if (market_cap and total_liabilities) else None
    e = safe_div(revenue_ttm, total_assets)

    # 5개 중 3개 이상 결측이면 의미 없음
    components = [a, b, c, d, e]
    if sum(x is None for x in components) >= 3:
        return None

    a = a if a is not None else 0.0
    b = b if b is not None else 0.0
    c = c if c is not None else 0.0
    d = d if d is not None else 0.0
    e = e if e is not None else 0.0

    return 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e


# ============================================================
# 시그널 분류 (각 지표별 individual rating)
# ============================================================
# 임계값 (UI에서 expander로 노출)
THRESHOLDS = {
    "debt_ratio":        {"strong": 0.40, "ok": 0.60},     # 낮을수록 좋음
    "current_ratio":     {"strong": 2.0,  "ok": 1.5,  "watch": 1.0},
    "quick_ratio":       {"strong": 1.0,  "ok": 0.7,  "watch": 0.5},
    "interest_coverage": {"strong": 8.0,  "ok": 3.0,  "watch": 1.5},
    "altman_z":          {"safe": 3.0,    "grey": 1.8},
    "net_debt_to_ebitda":{"strong": 1.5,  "ok": 3.0,  "watch": 4.5},  # 낮을수록 좋음
}

# 섹터 보정: 금융업은 자기 사업 모델상 부채비율이 정상적으로 높음
ELEVATED_DEBT_SECTORS = {"Financial Services", "Financials", "Banks", "Insurance"}
UTILITY_LIKE_SECTORS = {"Utilities", "Real Estate"}


def _rate_debt_ratio(v: Optional[float], sector: str = "") -> str:
    if v is None:
        return "unknown"
    if sector in ELEVATED_DEBT_SECTORS:
        return "sector_normal"  # 별도 처리
    # 유틸/리츠는 60% 까지는 정상
    if sector in UTILITY_LIKE_SECTORS:
        if v < 0.55: return "strong"
        if v < 0.70: return "ok"
        return "warning"
    t = THRESHOLDS["debt_ratio"]
    if v < t["strong"]: return "strong"
    if v < t["ok"]:     return "ok"
    return "warning"


def _rate_current_ratio(v: Optional[float]) -> str:
    if v is None: return "unknown"
    t = THRESHOLDS["current_ratio"]
    if v >= t["strong"]: return "strong"
    if v >= t["ok"]:     return "ok"
    if v >= t["watch"]:  return "watch"
    return "warning"


def _rate_quick_ratio(v: Optional[float]) -> str:
    if v is None: return "unknown"
    t = THRESHOLDS["quick_ratio"]
    if v >= t["strong"]: return "strong"
    if v >= t["ok"]:     return "ok"
    if v >= t["watch"]:  return "watch"
    return "warning"


def _rate_interest_coverage(v: Optional[float]) -> str:
    if v is None: return "unknown"
    t = THRESHOLDS["interest_coverage"]
    if v >= t["strong"]: return "strong"
    if v >= t["ok"]:     return "ok"
    if v >= t["watch"]:  return "watch"
    if v < 1.0:          return "distress"  # 영업이익으로 이자 못 갚음
    return "warning"


def _rate_altman_z(v: Optional[float]) -> str:
    if v is None: return "unknown"
    t = THRESHOLDS["altman_z"]
    if v >= t["safe"]: return "safe"
    if v >= t["grey"]: return "grey"
    return "distress"


def _rate_net_debt_ebitda(v: Optional[float]) -> str:
    if v is None: return "unknown"
    # 순현금(음수)이면 매우 양호
    if v < 0:                            return "net_cash"
    t = THRESHOLDS["net_debt_to_ebitda"]
    if v < t["strong"]: return "strong"
    if v < t["ok"]:     return "ok"
    if v < t["watch"]:  return "watch"
    return "warning"


# ============================================================
# 종합 4단계 판정
# ============================================================
def _classify_overall(ratings: dict, ic_rating: str) -> tuple[str, str]:
    """
    각 지표 rating을 모아서 종합 4단계 판정.

    Returns:
        (overall, explanation)
        overall ∈ {STABLE, ADEQUATE, STRESSED, DISTRESS}
    """
    # 이자 미충당 = 즉시 DISTRESS
    if ic_rating == "distress":
        return "DISTRESS", "영업이익으로 이자비용을 충당하지 못함 (interest coverage < 1.0)"

    # Altman distress = DISTRESS
    if ratings.get("altman_z") == "distress":
        return "DISTRESS", "Altman Z-Score 1.8 미만 (파산 위험 구간)"

    # 카운트
    severities = [
        ratings["debt_ratio"],
        ratings["current_ratio"],
        ratings["quick_ratio"],
        ic_rating,
    ]
    n_warning = sum(1 for r in severities if r == "warning")
    n_watch   = sum(1 for r in severities if r == "watch")

    if n_warning >= 2:
        return "DISTRESS", f"{n_warning}개 지표에서 경고 수준"
    if n_warning >= 1:
        return "STRESSED", f"{n_warning}개 지표 경고 + {n_watch}개 워치"
    if n_watch >= 2:
        return "STRESSED", f"{n_watch}개 지표 워치 수준"
    if n_watch == 1:
        return "ADEQUATE", "1개 지표 워치, 나머지 정상"
    return "STABLE", "모든 안정성 지표 정상 수준"


# ============================================================
# 해석 문자열
# ============================================================
def _build_interpretation(
    *,
    overall: str,
    overall_reason: str,
    debt_ratio: Optional[float],
    current_ratio: Optional[float],
    quick_ratio: Optional[float],
    interest_coverage: Optional[float],
    altman_z: Optional[float],
    net_debt_ebitda: Optional[float],
    sector: str,
) -> str:
    parts = []

    # 헤드라인
    headline_map = {
        "STABLE":   "재무 안정성 양호.",
        "ADEQUATE": "재무 안정성 적정 — 일부 항목 모니터링 필요.",
        "STRESSED": "재무 안정성 압박 — 단기 유동성 또는 부채 부담 확인 필요.",
        "DISTRESS": "재무 위험 — 부채 상환 능력 우려.",
    }
    parts.append(headline_map.get(overall, "재무 안정성 분석.") + f" ({overall_reason})")

    # 부채 구조
    if debt_ratio is not None:
        sector_note = ""
        if sector in ELEVATED_DEBT_SECTORS:
            sector_note = " (금융업 — 사업 모델상 정상)"
        elif sector in UTILITY_LIKE_SECTORS:
            sector_note = " (유틸/리츠 — 통상 50~70%)"
        parts.append(f"부채비율 {debt_ratio:.1%}{sector_note}.")

    # 유동성
    if current_ratio is not None and quick_ratio is not None:
        if quick_ratio >= 1.0:
            liq_desc = "단기 채무를 재고자산 없이도 현금성 자산으로 커버 가능."
        elif quick_ratio >= 0.5:
            liq_desc = "재고자산 회전에 일부 의존."
        else:
            liq_desc = "재고 처분 없이는 단기 채무 상환 어려움."
        parts.append(
            f"유동비율 {current_ratio:.2f}x / 당좌비율 {quick_ratio:.2f}x — {liq_desc}"
        )

    # 이자 보상
    if interest_coverage is not None:
        if interest_coverage >= 8.0:
            ic_desc = "이자 부담 매우 낮음 (영업이익의 1/8 이내)"
        elif interest_coverage >= 3.0:
            ic_desc = "이자 부담 통제 가능"
        elif interest_coverage >= 1.5:
            ic_desc = "이자 부담이 영업이익을 상당 부분 잠식"
        elif interest_coverage >= 1.0:
            ic_desc = "영업이익이 이자비용 수준 — 이익 변동에 취약"
        else:
            ic_desc = "영업이익 < 이자비용 — 추가 차입 또는 자산 매각 의존"
        parts.append(f"이자보상비율 {interest_coverage:.1f}x — {ic_desc}.")

    # 순부채/EBITDA
    if net_debt_ebitda is not None:
        if net_debt_ebitda < 0:
            parts.append(f"순부채/EBITDA {net_debt_ebitda:.1f}x (순현금 포지션).")
        elif net_debt_ebitda <= 3.0:
            parts.append(f"순부채/EBITDA {net_debt_ebitda:.1f}x — 적정 레버리지.")
        else:
            parts.append(f"순부채/EBITDA {net_debt_ebitda:.1f}x — 부채 과다 (3x 이상).")

    # Altman Z
    if altman_z is not None:
        if altman_z >= 3.0:
            z_desc = "Safe Zone"
        elif altman_z >= 1.8:
            z_desc = "Grey Zone (모니터링)"
        else:
            z_desc = "Distress Zone (파산 위험)"
        parts.append(f"Altman Z = {altman_z:.2f} ({z_desc}).")

    return " ".join(parts)


# ============================================================
# 메인: analyze()
# ============================================================
def analyze(
    balance_quarterly: pd.DataFrame,
    income_quarterly: pd.DataFrame,
    cashflow_quarterly: Optional[pd.DataFrame] = None,
    market_cap: Optional[float] = None,
    sector: str = "",
) -> dict:
    """
    재무 안정성 종합 분석.

    Args:
        balance_quarterly:  분기 BS (최신이 iloc[:, 0])
        income_quarterly:   분기 IS (TTM 계산용)
        cashflow_quarterly: 분기 CF (EBITDA 합성 시 D&A 보완)
        market_cap:         시가총액 (Altman D 계산용, 없으면 0 처리)
        sector:             섹터 (금융/유틸 보정용)

    Returns:
        {
            "metrics": { ... },
            "ratings": { ... },    # 각 지표 strong/ok/watch/warning/distress
            "overall": "STABLE" | "ADEQUATE" | "STRESSED" | "DISTRESS",
            "overall_reason": str,
            "interpretation": str,
            "flags": [{"severity": "info|warn|alert", "msg": "..."}],
        }
    """
    # ----- 원시 값 추출 -----
    total_assets        = _latest(balance_quarterly, "total_assets")
    total_liabilities   = _latest(balance_quarterly, "total_liabilities")
    stockholders_equity = _latest(balance_quarterly, "stockholders_equity")
    current_assets      = _latest(balance_quarterly, "current_assets")
    current_liabilities = _latest(balance_quarterly, "current_liabilities")
    inventory           = _latest(balance_quarterly, "inventory") or 0.0
    cash                = _latest(balance_quarterly, "cash") or 0.0
    retained_earnings   = _latest(balance_quarterly, "retained_earnings")
    total_debt          = _compose_total_debt(balance_quarterly)

    ebit_ttm            = _ttm(income_quarterly, "operating_income")
    interest_expense    = _ttm(income_quarterly, "interest_expense")
    revenue_ttm         = _ttm(income_quarterly, "revenue")
    ebitda_ttm          = _compose_ebitda(income_quarterly, cashflow_quarterly)

    # ----- Solvency 비율 -----
    debt_ratio    = safe_div(total_debt,          total_assets)
    equity_ratio  = safe_div(stockholders_equity, total_assets)
    debt_equity   = safe_div(total_debt,          stockholders_equity)

    # ----- Liquidity 비율 -----
    current_ratio = safe_div(current_assets,                current_liabilities)
    quick_ratio   = safe_div(
        (current_assets - inventory) if current_assets is not None else None,
        current_liabilities,
    )
    cash_ratio    = safe_div(cash, current_liabilities)

    # ----- Coverage -----
    # interest_expense는 yfinance에서 음수로 들어오기도 함 — 절대값
    if interest_expense is not None:
        interest_expense_abs = abs(interest_expense)
        # 0에 가까우면 의미 없음 (사실상 무차입)
        interest_coverage = safe_div(ebit_ttm, interest_expense_abs) if interest_expense_abs > 1e-6 else None
    else:
        interest_expense_abs = None
        interest_coverage = None

    # ----- Net Debt / EBITDA -----
    net_debt = (total_debt - cash) if total_debt is not None else None
    net_debt_ebitda = safe_div(net_debt, ebitda_ttm) if (net_debt is not None and ebitda_ttm and ebitda_ttm > 0) else None

    # ----- Altman Z -----
    altman_z = _altman_z(
        total_assets=total_assets,
        current_assets=current_assets,
        current_liabilities=current_liabilities,
        retained_earnings=retained_earnings,
        ebit_ttm=ebit_ttm,
        market_cap=market_cap,
        total_liabilities=total_liabilities,
        revenue_ttm=revenue_ttm,
    )

    # ----- 각 지표 rating -----
    ratings = {
        "debt_ratio":         _rate_debt_ratio(debt_ratio, sector),
        "current_ratio":      _rate_current_ratio(current_ratio),
        "quick_ratio":        _rate_quick_ratio(quick_ratio),
        "interest_coverage":  _rate_interest_coverage(interest_coverage),
        "altman_z":           _rate_altman_z(altman_z),
        "net_debt_to_ebitda": _rate_net_debt_ebitda(net_debt_ebitda),
    }

    # ----- 종합 판정 -----
    overall, overall_reason = _classify_overall(ratings, ratings["interest_coverage"])

    # ----- Flags -----
    flags: list[dict] = []
    if ratings["interest_coverage"] == "distress":
        flags.append({"severity": "alert",
                      "msg": "Interest coverage < 1.0 — 영업이익으로 이자 미충당"})
    elif ratings["interest_coverage"] == "warning":
        flags.append({"severity": "warn",
                      "msg": f"Interest coverage {interest_coverage:.1f}x — 이자 부담 가중 (CFA 임계 1.5x)"})

    if ratings["altman_z"] == "distress":
        flags.append({"severity": "alert",
                      "msg": f"Altman Z {altman_z:.2f} — 파산 위험 구간 (<1.8)"})
    elif ratings["altman_z"] == "grey":
        flags.append({"severity": "warn",
                      "msg": f"Altman Z {altman_z:.2f} — 그레이 존 (1.8~3.0)"})

    if ratings["quick_ratio"] == "warning":
        flags.append({"severity": "warn",
                      "msg": f"Quick ratio {quick_ratio:.2f}x — 단기 유동성 부족 (CFA 임계 0.5x)"})

    if ratings["debt_ratio"] == "warning" and sector not in ELEVATED_DEBT_SECTORS:
        flags.append({"severity": "warn",
                      "msg": f"Debt ratio {debt_ratio:.1%} — 부채 과다 (CFA 임계 60%)"})

    if ratings["net_debt_to_ebitda"] == "warning":
        flags.append({"severity": "warn",
                      "msg": f"Net Debt / EBITDA {net_debt_ebitda:.1f}x — 레버리지 과다 (>4.5x)"})

    if ratings["net_debt_to_ebitda"] == "net_cash":
        flags.append({"severity": "info",
                      "msg": "Net Cash 포지션 — 현금이 총부채 초과"})

    # ----- 해석 -----
    interpretation = _build_interpretation(
        overall=overall,
        overall_reason=overall_reason,
        debt_ratio=debt_ratio,
        current_ratio=current_ratio,
        quick_ratio=quick_ratio,
        interest_coverage=interest_coverage,
        altman_z=altman_z,
        net_debt_ebitda=net_debt_ebitda,
        sector=sector,
    )

    return {
        "metrics": {
            # Solvency
            "debt_ratio":         debt_ratio,
            "equity_ratio":       equity_ratio,
            "debt_to_equity":     debt_equity,
            "net_debt_to_ebitda": net_debt_ebitda,
            # Liquidity
            "current_ratio":      current_ratio,
            "quick_ratio":        quick_ratio,
            "cash_ratio":         cash_ratio,
            # Coverage
            "interest_coverage":  interest_coverage,
            # Composite
            "altman_z":           altman_z,
            # 원자료 (UI display용)
            "raw": {
                "total_assets":        total_assets,
                "total_liabilities":   total_liabilities,
                "total_debt":          total_debt,
                "stockholders_equity": stockholders_equity,
                "current_assets":      current_assets,
                "current_liabilities": current_liabilities,
                "inventory":           inventory,
                "cash":                cash,
                "ebit_ttm":            ebit_ttm,
                "ebitda_ttm":          ebitda_ttm,
                "interest_expense":    interest_expense_abs,
                "revenue_ttm":         revenue_ttm,
                "retained_earnings":   retained_earnings,
                "market_cap":          market_cap,
            },
        },
        "ratings": ratings,
        "overall": overall,
        "overall_reason": overall_reason,
        "interpretation": interpretation,
        "flags": flags,
        "thresholds": THRESHOLDS,  # UI에서 expander로 표시
    }


# ============================================================
# render_tab() — Streamlit UI (self-contained, app.py 헬퍼 의존 없음)
# ============================================================
# 본인 PROFITABILITY 탭과 동일한 다크 카드 디자인 (#141414 배경, #525252 테두리).
# app.py에서 import 한 줄 + 호출 한 줄로 끝.

CARD_OPEN = (
    '<div style="background:#141414;border:1px solid #525252;'
    'border-radius:6px;padding:18px 22px;margin-bottom:16px;">'
    '<div style="color:#fff;font-size:11px;letter-spacing:2px;'
    'border-bottom:1px solid #404040;padding-bottom:8px;'
    'margin-bottom:14px;font-weight:600;">{title}</div>'
)
CARD_CLOSE = '</div>'

# rating → 색상 매핑 (4ade80=green, fbbf24=amber, ef4444=red 등)
_RATING_COLOR = {
    "strong": "#4ade80", "safe": "#4ade80", "net_cash": "#4ade80",
    "ok": "#a3e635",
    "info": "#d4d4d8",
    "sector_normal": "#a3a3a3",
    "grey": "#fbbf24", "watch": "#fbbf24",
    "warning": "#f97316",
    "distress": "#ef4444",
    "unknown": "#525252",
}
_RATING_LABEL = {
    "strong": "STRONG", "safe": "SAFE", "net_cash": "NET CASH",
    "ok": "OK",
    "sector_normal": "SECTOR NORMAL",
    "grey": "GREY", "watch": "WATCH",
    "warning": "WARN",
    "distress": "DISTRESS",
    "unknown": "—", "info": "",
}

_FINANCIAL_SECTORS = {"Financial Services", "Financials", "Banks", "Insurance"}


def _fmt_money(v) -> str:
    if v is None:
        return "—"
    av = abs(v)
    if av >= 1e9:  return f"{v/1e9:,.2f}B"
    if av >= 1e6:  return f"{v/1e6:,.2f}M"
    if av >= 1e3:  return f"{v/1e3:,.1f}K"
    return f"{v:,.0f}"


def _metric_line(label: str, value: str, rating: str, note: str = "") -> str:
    """단일 메트릭 한 줄 HTML."""
    color = _RATING_COLOR.get(rating, "#d4d4d8")
    rl = _RATING_LABEL.get(rating, "")
    rating_html = (f'&nbsp;<span style="color:{color};font-size:10px;'
                   f'letter-spacing:1px;">{rl}</span>') if rl else ""
    note_html = (f'<div style="color:#737373;font-size:10px;margin-top:2px;">'
                 f'{note}</div>') if note else ""
    return (
        f'<div style="margin-bottom:14px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;">'
        f'<div style="color:#a3a3a3;font-size:12px;">{label}</div>'
        f'<div><span style="color:{color};font-size:18px;font-weight:600;">'
        f'{value}</span>{rating_html}</div>'
        f'</div>{note_html}</div>'
    )


def render_tab(data: dict) -> None:
    """
    STABILITY 탭 렌더. app.py에서 다음과 같이 사용:

        from modules.stability_analysis import render_tab as render_stability_tab
        ...
        with tab_stab:
            render_stability_tab(data)

    Args:
        data: data_loader의 표준 스키마 (balance_quarterly, income_quarterly,
              cashflow_quarterly, meta.{sector_yf, market_cap, ...} 포함)
    """
    import streamlit as st

    balance_q  = data.get("balance_quarterly")
    income_q   = data.get("income_quarterly")
    cashflow_q = data.get("cashflow_quarterly")
    meta       = data.get("meta", {}) or {}
    sector     = meta.get("sector_yf") or meta.get("sector") or ""
    market_cap = meta.get("market_cap") or meta.get("marketCap")

    if balance_q is None or balance_q.empty or income_q is None or income_q.empty:
        st.warning("Stability 분석 불가 — 재무제표 데이터 부족")
        return

    # 분석
    try:
        result = analyze(
            balance_quarterly=balance_q,
            income_quarterly=income_q,
            cashflow_quarterly=cashflow_q,
            market_cap=market_cap,
            sector=sector,
        )
    except Exception as e:
        st.error(f"Stability 분석 실패: {e}")
        return

    m       = result["metrics"]
    ratings = result["ratings"]
    overall = result["overall"]
    flags   = result["flags"]
    raw     = m["raw"]

    is_financial = sector in _FINANCIAL_SECTORS

    # ============================================================
    # CARD 1: OVERALL ASSESSMENT
    # ============================================================
    overall_color = {
        "STABLE":   "#4ade80",
        "ADEQUATE": "#a3e635",
        "STRESSED": "#fbbf24",
        "DISTRESS": "#ef4444",
    }.get(overall, "#d4d4d8")

    st.markdown(CARD_OPEN.format(title="STABILITY ASSESSMENT"), unsafe_allow_html=True)

    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(
            f'<div style="border:1px solid {overall_color};color:{overall_color};'
            f'padding:6px 12px;border-radius:4px;font-size:12px;font-weight:700;'
            f'letter-spacing:2px;display:inline-block;">{overall}</div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div style="color:#d4d4d8;font-size:14px;line-height:1.6;">'
            f'{result["interpretation"]}</div>',
            unsafe_allow_html=True,
        )

    # Flags
    if flags:
        st.markdown('<div style="margin-top:12px;"></div>', unsafe_allow_html=True)
        for f in flags:
            sev = f.get("severity", "info")
            color = {"alert": "#ef4444", "warn": "#fbbf24", "info": "#60a5fa"}.get(sev, "#a3a3a3")
            st.markdown(
                f'<div style="margin-bottom:6px;font-size:13px;">'
                f'<span style="color:{color};font-weight:600;">[{sev.upper()}]</span> '
                f'<span style="color:#d4d4d8;">{f.get("msg", "")}</span></div>',
                unsafe_allow_html=True,
            )

    st.markdown(CARD_CLOSE, unsafe_allow_html=True)

    # ============================================================
    # CARD 2 & 3: SOLVENCY (좌) + LIQUIDITY (우)
    # ============================================================
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown(CARD_OPEN.format(title="SOLVENCY — 장기 안정성"), unsafe_allow_html=True)
        # Debt Ratio
        dr = m["debt_ratio"]
        if dr is None:
            html = _metric_line("Debt Ratio", "N/A", "unknown")
        elif is_financial:
            html = _metric_line("Debt Ratio", f"{dr:.1%}", "sector_normal",
                                note="금융업 — 사업 모델상 정상")
        else:
            html = _metric_line("Debt Ratio", f"{dr:.1%}", ratings["debt_ratio"],
                                note="Total Debt / Total Assets")
        # Equity Ratio
        er = m["equity_ratio"]
        if er is not None:
            html += _metric_line("Equity Ratio", f"{er:.1%}", "info",
                                 note="Stockholders Equity / Total Assets")
        # D/E
        de = m["debt_to_equity"]
        if de is not None:
            html += _metric_line("Debt / Equity", f"{de:.2f}x", "info",
                                 note="Total Debt / Equity")
        # Net Debt / EBITDA
        nde = m["net_debt_to_ebitda"]
        if nde is None:
            html += _metric_line("Net Debt / EBITDA", "N/A", "unknown")
        else:
            disp = f"{nde:.2f}x" if nde >= 0 else f"({abs(nde):.2f}x) Net Cash"
            html += _metric_line("Net Debt / EBITDA", disp,
                                 ratings["net_debt_to_ebitda"],
                                 note="(Total Debt - Cash) / EBITDA (TTM)")
        st.markdown(html, unsafe_allow_html=True)
        st.markdown(CARD_CLOSE, unsafe_allow_html=True)

    with col_right:
        st.markdown(CARD_OPEN.format(title="LIQUIDITY — 단기 유동성"), unsafe_allow_html=True)
        # Current Ratio
        cr = m["current_ratio"]
        if cr is not None:
            html = _metric_line("Current Ratio", f"{cr:.2f}x",
                                ratings["current_ratio"],
                                note="Current Assets / Current Liabilities")
        else:
            html = _metric_line("Current Ratio", "N/A", "unknown")
        # Quick Ratio
        qr = m["quick_ratio"]
        if qr is not None:
            html += _metric_line("Quick Ratio", f"{qr:.2f}x",
                                 ratings["quick_ratio"],
                                 note="(CA - Inventory) / CL")
        else:
            html += _metric_line("Quick Ratio", "N/A", "unknown")
        # Cash Ratio
        cash_r = m["cash_ratio"]
        if cash_r is not None:
            html += _metric_line("Cash Ratio", f"{cash_r:.2f}x", "info",
                                 note="Cash / Current Liabilities")
        # Interest Coverage
        ic = m["interest_coverage"]
        if ic is None:
            html += _metric_line("Interest Coverage", "N/A", "unknown",
                                 note="이자비용 사실상 없음")
        else:
            html += _metric_line("Interest Coverage", f"{ic:.2f}x",
                                 ratings["interest_coverage"],
                                 note="EBIT (TTM) / Interest Expense (TTM)")
        st.markdown(html, unsafe_allow_html=True)
        st.markdown(CARD_CLOSE, unsafe_allow_html=True)

    # ============================================================
    # CARD 4: ALTMAN Z-SCORE (composite)
    # ============================================================
    st.markdown(CARD_OPEN.format(title="ALTMAN Z-SCORE — 종합 파산 위험"), unsafe_allow_html=True)
    z = m["altman_z"]
    if is_financial:
        st.markdown(
            '<div style="color:#a3a3a3;font-size:13px;">'
            'N/A — 금융업은 Altman 모델(비금융 제조업 기반) 비적용</div>',
            unsafe_allow_html=True,
        )
    elif z is None:
        st.markdown(
            '<div style="color:#a3a3a3;font-size:13px;">'
            'N/A — Altman Z 계산에 필요한 데이터 부족</div>',
            unsafe_allow_html=True,
        )
    else:
        z_zone = "Safe Zone" if z >= 3.0 else ("Grey Zone" if z >= 1.8 else "Distress Zone")
        z_color = _RATING_COLOR[ratings["altman_z"]]
        st.markdown(
            f'<div style="display:flex;align-items:baseline;gap:18px;">'
            f'<div style="color:{z_color};font-size:36px;font-weight:700;">{z:.2f}</div>'
            f'<div style="color:{z_color};font-size:14px;font-weight:600;'
            f'letter-spacing:1px;">{z_zone}</div>'
            f'</div>'
            f'<div style="color:#737373;font-size:11px;margin-top:8px;">'
            f'Z = 1.2(WC/TA) + 1.4(RE/TA) + 3.3(EBIT/TA) + 0.6(MktCap/Liab) + 1.0(Rev/TA)'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.markdown(CARD_CLOSE, unsafe_allow_html=True)

    # ============================================================
    # Signal thresholds (transparency)
    # ============================================================
    with st.expander("Signal thresholds (CFA 표준)"):
        st.markdown("""
| 지표 | strong | ok | watch | warning | distress |
|---|---|---|---|---|---|
| Debt Ratio | <40% | 40~60% | — | >60% | — |
| Current Ratio | >2.0x | 1.5~2.0x | 1.0~1.5x | <1.0x | — |
| Quick Ratio | >1.0x | 0.7~1.0x | 0.5~0.7x | <0.5x | — |
| Interest Coverage | >8x | 3~8x | 1.5~3x | <1.5x | <1.0x |
| Net Debt / EBITDA | <1.5x | 1.5~3x | 3~4.5x | >4.5x | — |
| Altman Z | safe >3.0 | — | grey 1.8~3.0 | — | <1.8 |

**섹터 보정:** 금융업 부채비율은 `sector_normal` (warning 미발동) ·
유틸/리츠는 strong<55%, ok<70% (완화).

**종합 4단계:**
- **STABLE**: 모든 지표 정상
- **ADEQUATE**: 1개 watch
- **STRESSED**: 2개+ watch 또는 1개 warning
- **DISTRESS**: 2개+ warning, IC<1.0, 또는 Altman <1.8
""")

    # Evidence
    with st.expander("Evidence — 원자료"):
        st.markdown(f"""
| 항목 | 값 |
|---|---|
| Total Assets | {_fmt_money(raw['total_assets'])} |
| Total Liabilities | {_fmt_money(raw['total_liabilities'])} |
| Total Debt | {_fmt_money(raw['total_debt'])} |
| Stockholders Equity | {_fmt_money(raw['stockholders_equity'])} |
| Current Assets | {_fmt_money(raw['current_assets'])} |
| Current Liabilities | {_fmt_money(raw['current_liabilities'])} |
| Inventory | {_fmt_money(raw['inventory'])} |
| Cash | {_fmt_money(raw['cash'])} |
| EBIT (TTM) | {_fmt_money(raw['ebit_ttm'])} |
| EBITDA (TTM) | {_fmt_money(raw['ebitda_ttm'])} |
| Interest Expense (TTM) | {_fmt_money(raw['interest_expense'])} |
| Revenue (TTM) | {_fmt_money(raw['revenue_ttm'])} |
| Retained Earnings | {_fmt_money(raw['retained_earnings'])} |
| Market Cap | {_fmt_money(raw['market_cap'])} |
""")
