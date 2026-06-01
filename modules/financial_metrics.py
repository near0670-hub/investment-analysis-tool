"""
modules/financial_metrics.py — 공통 재무 지표 계산 헬퍼

다른 분석 모듈들이 의존하는 기반 모듈.
yfinance 표준 스키마(영문 행 이름)에서 안전하게 값 추출 + TTM 계산 + 공통 비율.

핵심 책임:
1. yfinance/DART 병합 데이터프레임에서 항목명 변동에 대응한 안전한 추출
2. TTM (Trailing Twelve Months) = 최근 4분기 합계
3. 공통 비율 (GPM, OPM, NPM 등)

표준 입력: data_loader.load_company_data() 가 반환하는 dict
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from utils.validation import safe_divide


# ============================================================
# yfinance 행 이름 alias (yfinance가 가끔 표기 변경)
# 같은 의미의 여러 이름을 시도해서 첫 번째 hit 사용
# ============================================================
INCOME_ROW_ALIASES = {
    "revenue":          ["Total Revenue", "Revenue", "Operating Revenue"],
    "cogs":             ["Cost Of Revenue", "Cost of Revenue", "Reconciled Cost Of Revenue"],
    "gross_profit":     ["Gross Profit"],
    "operating_income": ["Operating Income", "Operating Income (Loss)", "Total Operating Income As Reported"],
    "operating_expense": ["Operating Expense", "Total Operating Expense"],
    "net_income":       ["Net Income", "Net Income Common Stockholders",
                         "Net Income Continuous Operations",
                         "Net Income From Continuing Operation Net Minority Interest"],
    "pretax_income":    ["Pretax Income", "Income Before Tax"],
    "tax_provision":    ["Tax Provision", "Income Tax Expense"],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
    "ebitda":           ["EBITDA", "Normalized EBITDA"],
    "ebit":             ["EBIT", "Operating Income"],
    "basic_eps":        ["Basic EPS"],
    "diluted_eps":      ["Diluted EPS"],
    "depreciation":     ["Reconciled Depreciation", "Depreciation And Amortization",
                         "Depreciation Amortization Depletion"],
    "rd_expense":       ["Research And Development", "Research Development"],
    "sga_expense":      ["Selling General And Administration", "Selling General And Administrative"],
}

BALANCE_ROW_ALIASES = {
    "total_assets":      ["Total Assets"],
    "current_assets":    ["Current Assets", "Total Current Assets"],
    "total_liabilities": ["Total Liabilities Net Minority Interest",
                          "Total Liabilities", "Total Liab"],
    "current_liab":      ["Current Liabilities", "Total Current Liabilities"],
    "stockholders_equity": ["Stockholders Equity", "Total Stockholder Equity",
                            "Common Stock Equity"],
    "cash":              ["Cash And Cash Equivalents", "Cash",
                          "Cash Cash Equivalents And Short Term Investments"],
    "inventory":         ["Inventory"],
    "receivables":       ["Accounts Receivable", "Receivables"],
    "total_debt":        ["Total Debt", "Net Debt"],
    "long_term_debt":    ["Long Term Debt"],
    "current_debt":      ["Current Debt", "Short Long Term Debt"],
    "shares_outstanding": ["Ordinary Shares Number", "Share Issued"],
}

CASHFLOW_ROW_ALIASES = {
    "operating_cf":  ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
                      "Total Cash From Operating Activities"],
    "investing_cf":  ["Investing Cash Flow", "Cash Flow From Continuing Investing Activities"],
    "financing_cf":  ["Financing Cash Flow", "Cash Flow From Continuing Financing Activities"],
    "capex":         ["Capital Expenditure", "Capital Expenditures"],
    "free_cash_flow": ["Free Cash Flow"],
    "dividends_paid": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
    "buyback":       ["Repurchase Of Capital Stock", "Common Stock Repurchase"],
}


# ============================================================
# 안전한 항목 추출
# ============================================================
def get_row_value(df: pd.DataFrame, aliases: list[str],
                  col_index: int = 0) -> Optional[float]:
    """
    DataFrame에서 alias 리스트의 첫 번째 hit 값을 반환.

    Args:
        df:        yfinance 재무제표 DataFrame (행=항목명, 열=날짜)
        aliases:   가능한 행 이름 리스트 (위에서 첫 번째 hit 사용)
        col_index: 열 인덱스 (0 = 가장 최근)

    Returns:
        값 또는 None
    """
    if df is None or df.empty:
        return None
    if col_index >= len(df.columns):
        return None

    for name in aliases:
        if name in df.index:
            try:
                value = df.loc[name].iloc[col_index]
                if pd.isna(value):
                    return None
                return float(value)
            except (KeyError, IndexError, ValueError, TypeError):
                continue
    return None


def get_row_series(df: pd.DataFrame, aliases: list[str]) -> pd.Series:
    """
    DataFrame에서 alias hit한 행 전체를 Series로 반환 (시계열 분석용).
    열 순서대로 (최근 → 과거).
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)
    for name in aliases:
        if name in df.index:
            return df.loc[name].astype(float, errors="ignore")
    return pd.Series(dtype=float)


# ============================================================
# 편의 함수 — alias 키로 접근
# ============================================================
def income(df: pd.DataFrame, key: str, col: int = 0) -> Optional[float]:
    """손익계산서 항목 추출. key는 INCOME_ROW_ALIASES의 키."""
    aliases = INCOME_ROW_ALIASES.get(key)
    if not aliases:
        raise KeyError(f"Unknown income key: {key}")
    return get_row_value(df, aliases, col)


def balance(df: pd.DataFrame, key: str, col: int = 0) -> Optional[float]:
    """재무상태표 항목 추출."""
    aliases = BALANCE_ROW_ALIASES.get(key)
    if not aliases:
        raise KeyError(f"Unknown balance key: {key}")
    return get_row_value(df, aliases, col)


def cashflow(df: pd.DataFrame, key: str, col: int = 0) -> Optional[float]:
    """현금흐름표 항목 추출."""
    aliases = CASHFLOW_ROW_ALIASES.get(key)
    if not aliases:
        raise KeyError(f"Unknown cashflow key: {key}")
    return get_row_value(df, aliases, col)


# ============================================================
# TTM (Trailing Twelve Months) — 최근 4분기 합
# ============================================================
def ttm_sum(quarterly_df: pd.DataFrame, key: str,
            row_aliases: dict[str, list[str]] = INCOME_ROW_ALIASES) -> Optional[float]:
    """
    최근 4분기 합계. 손익계산서/현금흐름표 항목에 사용.
    재무상태표(스톡 변수)에는 사용하지 말 것 — 그건 TTM 평균을 써야 함.

    >>> ttm_sum(income_quarterly, "revenue")  # 최근 4분기 매출 합
    """
    aliases = row_aliases.get(key)
    if not aliases:
        raise KeyError(f"Unknown key: {key}")

    if quarterly_df is None or quarterly_df.empty:
        return None
    if len(quarterly_df.columns) < 4:
        return None  # 4분기 안 됨

    series = get_row_series(quarterly_df, aliases)
    if series.empty:
        return None

    recent_4 = series.iloc[:4]
    if recent_4.isna().any():
        return None  # 결측이 있으면 합계 의미 없음

    return float(recent_4.sum())


def ttm_avg(quarterly_df: pd.DataFrame, key: str,
            row_aliases: dict[str, list[str]] = BALANCE_ROW_ALIASES) -> Optional[float]:
    """
    최근 4분기(또는 5분기) 평균. 재무상태표의 스톡 변수에 사용.
    ROE/ROA 계산에서 자본/자산은 기간 평균을 쓰는 게 정확.

    >>> ttm_avg(balance_quarterly, "stockholders_equity")
    """
    aliases = row_aliases.get(key)
    if not aliases:
        raise KeyError(f"Unknown key: {key}")

    if quarterly_df is None or quarterly_df.empty:
        return None

    series = get_row_series(quarterly_df, aliases)
    if series.empty:
        return None

    # 최근 5분기 중 결측 제외한 평균 (또는 단일값)
    recent = series.iloc[:5].dropna()
    if recent.empty:
        return None

    return float(recent.mean())


def ttm_latest(quarterly_df: pd.DataFrame, key: str,
               row_aliases: dict[str, list[str]] = BALANCE_ROW_ALIASES) -> Optional[float]:
    """가장 최근 분기말 값 (스톡 변수의 기말잔액)."""
    return get_row_value(quarterly_df, row_aliases.get(key, []), col_index=0)


# ============================================================
# 공통 비율
# ============================================================
def gross_margin(income_df: pd.DataFrame, use_ttm: bool = True) -> Optional[float]:
    """매출총이익률 = 매출총이익 / 매출"""
    if use_ttm:
        revenue = ttm_sum(income_df, "revenue", INCOME_ROW_ALIASES)
        gp = ttm_sum(income_df, "gross_profit", INCOME_ROW_ALIASES)
    else:
        revenue = income(income_df, "revenue")
        gp = income(income_df, "gross_profit")
    return safe_divide(gp, revenue)


def operating_margin(income_df: pd.DataFrame, use_ttm: bool = True) -> Optional[float]:
    """영업이익률"""
    if use_ttm:
        revenue = ttm_sum(income_df, "revenue", INCOME_ROW_ALIASES)
        op = ttm_sum(income_df, "operating_income", INCOME_ROW_ALIASES)
    else:
        revenue = income(income_df, "revenue")
        op = income(income_df, "operating_income")
    return safe_divide(op, revenue)


def net_margin(income_df: pd.DataFrame, use_ttm: bool = True) -> Optional[float]:
    """순이익률"""
    if use_ttm:
        revenue = ttm_sum(income_df, "revenue", INCOME_ROW_ALIASES)
        ni = ttm_sum(income_df, "net_income", INCOME_ROW_ALIASES)
    else:
        revenue = income(income_df, "revenue")
        ni = income(income_df, "net_income")
    return safe_divide(ni, revenue)


def free_cash_flow(cashflow_df: pd.DataFrame, use_ttm: bool = True) -> Optional[float]:
    """
    FCF = 영업CF - CapEx.
    yfinance가 "Free Cash Flow"를 직접 제공할 때도 있지만, 계산이 더 안전.
    """
    if use_ttm:
        ocf = ttm_sum(cashflow_df, "operating_cf", CASHFLOW_ROW_ALIASES)
        capex = ttm_sum(cashflow_df, "capex", CASHFLOW_ROW_ALIASES)
    else:
        ocf = cashflow(cashflow_df, "operating_cf")
        capex = cashflow(cashflow_df, "capex")

    if ocf is None:
        return None

    # CapEx는 yfinance에서 음수로 옴 (지출). 그래서 + 가 정상.
    # 일부 출처는 양수로 오니, abs 처리하고 빼는 게 안전.
    if capex is None:
        return ocf
    return ocf - abs(capex)


def ebitda(income_df: pd.DataFrame, cashflow_df: pd.DataFrame,
           use_ttm: bool = True) -> Optional[float]:
    """
    EBITDA. yfinance가 직접 제공하지 않으면 영업이익 + 감가상각 으로 추정.
    """
    # 직접 제공 시
    direct = ttm_sum(income_df, "ebitda", INCOME_ROW_ALIASES) if use_ttm \
             else income(income_df, "ebitda")
    if direct is not None and direct > 0:
        return direct

    # 추정: 영업이익 + 감가상각
    if use_ttm:
        op = ttm_sum(income_df, "operating_income", INCOME_ROW_ALIASES)
        dep = ttm_sum(income_df, "depreciation", INCOME_ROW_ALIASES)
    else:
        op = income(income_df, "operating_income")
        dep = income(income_df, "depreciation")

    if op is None:
        return None
    return op + (dep or 0)


def net_debt(balance_df: pd.DataFrame) -> Optional[float]:
    """순차입금 = 총차입금 - 현금성자산. (음수면 순현금)"""
    debt = balance(balance_df, "total_debt")
    cash = balance(balance_df, "cash")

    if debt is None and cash is None:
        return None

    # 단기차입금 + 장기차입금 fallback
    if debt is None:
        st = balance(balance_df, "current_debt") or 0
        lt = balance(balance_df, "long_term_debt") or 0
        if st == 0 and lt == 0:
            return None
        debt = st + lt

    if cash is None:
        cash = 0

    return debt - cash


def enterprise_value(market_cap: Optional[float],
                     balance_df: pd.DataFrame) -> Optional[float]:
    """EV = 시총 + 순차입금"""
    if market_cap is None:
        return None
    nd = net_debt(balance_df) or 0
    return market_cap + nd


# ============================================================
# 패키지된 기본 지표 (다른 모듈이 한 번에 받아갈 때 편리)
# ============================================================
def compute_base_metrics(data: dict) -> dict:
    """
    data_loader 결과 dict → 자주 쓰는 기본 지표 한 묶음.

    다른 분석 모듈들이 이걸 호출해서 공통으로 사용.
    """
    income_q = data.get("income_quarterly", pd.DataFrame())
    income_a = data.get("income_annual", pd.DataFrame())
    balance_q = data.get("balance_quarterly", pd.DataFrame())
    cashflow_q = data.get("cashflow_quarterly", pd.DataFrame())

    market_cap = data.get("meta", {}).get("market_cap")

    return {
        # TTM 손익
        "revenue_ttm":          ttm_sum(income_q, "revenue", INCOME_ROW_ALIASES),
        "gross_profit_ttm":     ttm_sum(income_q, "gross_profit", INCOME_ROW_ALIASES),
        "operating_income_ttm": ttm_sum(income_q, "operating_income", INCOME_ROW_ALIASES),
        "net_income_ttm":       ttm_sum(income_q, "net_income", INCOME_ROW_ALIASES),
        "ebitda_ttm":           ebitda(income_q, cashflow_q, use_ttm=True),
        "interest_expense_ttm": ttm_sum(income_q, "interest_expense", INCOME_ROW_ALIASES),

        # TTM 현금흐름
        "operating_cf_ttm": ttm_sum(cashflow_q, "operating_cf", CASHFLOW_ROW_ALIASES),
        "capex_ttm":        ttm_sum(cashflow_q, "capex", CASHFLOW_ROW_ALIASES),
        "fcf_ttm":          free_cash_flow(cashflow_q, use_ttm=True),

        # 재무상태 (최근 분기 + 평균)
        "total_assets_latest":  ttm_latest(balance_q, "total_assets"),
        "total_assets_avg":     ttm_avg(balance_q, "total_assets"),
        "equity_latest":        ttm_latest(balance_q, "stockholders_equity"),
        "equity_avg":           ttm_avg(balance_q, "stockholders_equity"),
        "current_assets":       balance(balance_q, "current_assets"),
        "current_liab":         balance(balance_q, "current_liab"),
        "total_liabilities":    balance(balance_q, "total_liabilities"),
        "inventory":            balance(balance_q, "inventory"),
        "receivables":          balance(balance_q, "receivables"),
        "cash":                 balance(balance_q, "cash"),
        "total_debt":           balance(balance_q, "total_debt"),

        # 파생
        "net_debt":         net_debt(balance_q),
        "enterprise_value": enterprise_value(market_cap, balance_q),

        # 마진
        "gross_margin":     gross_margin(income_q, use_ttm=True),
        "operating_margin": operating_margin(income_q, use_ttm=True),
        "net_margin":       net_margin(income_q, use_ttm=True),

        # 메타
        "market_cap": market_cap,
    }
