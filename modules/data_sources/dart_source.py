"""
modules/data_sources/dart_source.py — DART (한국 공시) 전담 소스

OpenDartReader로 한국 종목의 재무제표 / 공시를 가져와서,
yfinance 스키마와 호환되는 형태로 정규화.

DART 계정과목 → yfinance 영문 항목 매핑이 핵심.
DART API 키는 https://opendart.fss.or.kr 에서 무료 발급.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from config import DART_API_KEY, DART_DEFAULT_FS_DIV


# ============================================================
# DART 계정과목 → yfinance 영문 매핑
# yfinance의 income_statement / balance_sheet 행 이름과 통일
# ============================================================
DART_TO_YF_INCOME = {
    "매출액":               "Total Revenue",
    "수익(매출액)":          "Total Revenue",
    "영업수익":             "Total Revenue",
    "매출원가":             "Cost Of Revenue",
    "매출총이익":            "Gross Profit",
    "판매비와관리비":         "Operating Expense",
    "영업이익":             "Operating Income",
    "영업이익(손실)":         "Operating Income",
    "당기순이익":            "Net Income",
    "당기순이익(손실)":       "Net Income",
    "법인세비용차감전순이익":  "Pretax Income",
    "법인세비용":            "Tax Provision",
    "이자수익":             "Interest Income",
    "이자비용":             "Interest Expense",
    "주당이익":             "Basic EPS",
    "기본주당이익":          "Basic EPS",
    "희석주당이익":          "Diluted EPS",
}

DART_TO_YF_BALANCE = {
    "자산총계":             "Total Assets",
    "유동자산":             "Current Assets",
    "비유동자산":            "Total Non Current Assets",
    "재고자산":             "Inventory",
    "매출채권":             "Accounts Receivable",
    "매출채권및기타채권":      "Accounts Receivable",
    "현금및현금성자산":       "Cash And Cash Equivalents",
    "부채총계":             "Total Liabilities Net Minority Interest",
    "유동부채":             "Current Liabilities",
    "비유동부채":            "Total Non Current Liabilities Net Minority Interest",
    "단기차입금":            "Current Debt",
    "장기차입금":            "Long Term Debt",
    "자본총계":             "Stockholders Equity",
    "자본금":               "Common Stock",
    "이익잉여금":            "Retained Earnings",
}

DART_TO_YF_CASHFLOW = {
    "영업활동현금흐름":       "Operating Cash Flow",
    "영업활동으로인한현금흐름": "Operating Cash Flow",
    "투자활동현금흐름":       "Investing Cash Flow",
    "투자활동으로인한현금흐름": "Investing Cash Flow",
    "재무활동현금흐름":       "Financing Cash Flow",
    "재무활동으로인한현금흐름": "Financing Cash Flow",
    "유형자산의취득":         "Capital Expenditure",
    "유형자산의처분":         "Sale Of PPE",
}


def is_dart_available() -> tuple[bool, str]:
    """DART 사용 가능 여부 + 이유"""
    if not DART_API_KEY:
        return False, "DART_API_KEY가 설정되지 않음 (환경변수 또는 .env 확인)"
    try:
        import OpenDartReader  # noqa: F401
    except ImportError:
        return False, "OpenDartReader 패키지 미설치 (pip install OpenDartReader)"
    return True, "OK"


def _extract_korean_code(ticker: str) -> Optional[str]:
    """'005930.KS' → '005930'. 한국 종목이 아니면 None."""
    upper = ticker.upper()
    if upper.endswith(".KS") or upper.endswith(".KQ"):
        return upper.split(".")[0]
    return None


def fetch_dart(ticker: str, verbose: bool = False) -> dict:
    """
    DART에서 한국 종목 재무제표 수집.

    Returns:
        dict: 정규화된 재무 데이터 (yfinance 스키마와 호환)
              실패 시 빈 DataFrame들로 채워진 dict 반환
    """
    empty_result = {
        "income_quarterly":   pd.DataFrame(),
        "income_annual":      pd.DataFrame(),
        "balance_quarterly":  pd.DataFrame(),
        "balance_annual":     pd.DataFrame(),
        "cashflow_quarterly": pd.DataFrame(),
        "cashflow_annual":    pd.DataFrame(),
        "company_info":       {},
        "recent_filings":     pd.DataFrame(),
    }

    # 1. 한국 종목인지 확인
    code = _extract_korean_code(ticker)
    if code is None:
        if verbose:
            print(f"  [DART SKIP] {ticker}는 한국 종목이 아님")
        return empty_result

    # 2. DART 사용 가능 여부 확인
    available, msg = is_dart_available()
    if not available:
        if verbose:
            print(f"  [DART SKIP] {msg}")
        return empty_result

    # 3. OpenDartReader 초기화 + 데이터 수집
    try:
        import OpenDartReader
        dart = OpenDartReader(DART_API_KEY)
    except Exception as e:
        if verbose:
            print(f"  [DART ERROR] 초기화 실패: {e}")
        return empty_result

    result = empty_result.copy()

    # 회사 기본 정보
    try:
        info = dart.company(code)
        if info is not None:
            result["company_info"] = dict(info) if hasattr(info, "to_dict") else info
    except Exception as e:
        if verbose:
            print(f"  [DART WARN] company info failed: {e}")

    # 최근 공시 목록 (최근 90일)
    try:
        from datetime import datetime, timedelta
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        filings = dart.list(code, start=start, end=end)
        if filings is not None and not filings.empty:
            result["recent_filings"] = filings
    except Exception as e:
        if verbose:
            print(f"  [DART WARN] filings failed: {e}")

    # 연간 재무제표 (최근 3년)
    try:
        current_year = pd.Timestamp.now().year
        annual_data = _fetch_annual_financials(dart, code, current_year, verbose=verbose)
        result["income_annual"]   = annual_data["income"]
        result["balance_annual"]  = annual_data["balance"]
        result["cashflow_annual"] = annual_data["cashflow"]
    except Exception as e:
        if verbose:
            print(f"  [DART WARN] annual financials failed: {e}")

    # 분기 재무제표 (최근 8분기)
    try:
        quarterly_data = _fetch_quarterly_financials(dart, code, verbose=verbose)
        result["income_quarterly"]   = quarterly_data["income"]
        result["balance_quarterly"]  = quarterly_data["balance"]
        result["cashflow_quarterly"] = quarterly_data["cashflow"]
    except Exception as e:
        if verbose:
            print(f"  [DART WARN] quarterly financials failed: {e}")

    return result


def _fetch_annual_financials(dart, code: str, current_year: int,
                             verbose: bool = False) -> dict:
    """
    최근 3개 사업연도의 연간 재무제표를 수집해 yfinance 형식 DataFrame으로 정규화.

    yfinance 스키마:
      - 행: 항목명 (예: "Total Revenue")
      - 열: 보고일자 (Timestamp)
      - 값: 금액 (원)
    """
    income_rows = {}
    balance_rows = {}
    cashflow_rows = {}
    columns = []

    for year_offset in range(0, 3):
        year = current_year - 1 - year_offset  # 작년부터 역순
        try:
            fs = dart.finstate_all(code, year, reprt_code="11011",
                                   fs_div=DART_DEFAULT_FS_DIV)
        except Exception as e:
            if verbose:
                print(f"    [DART] {year}년 재무제표 조회 실패: {e}")
            continue

        if fs is None or fs.empty:
            continue

        col_ts = pd.Timestamp(f"{year}-12-31")
        columns.append(col_ts)

        # account_nm (계정명) + thstrm_amount (당기금액)
        for _, row in fs.iterrows():
            account_nm = row.get("account_nm", "")
            try:
                amount = float(str(row.get("thstrm_amount", "0")).replace(",", ""))
            except (ValueError, TypeError):
                amount = None

            # 재무제표 구분 (BS / IS / CIS / CF)
            sj_div = row.get("sj_div", "")

            if sj_div == "IS" or sj_div == "CIS":  # 손익계산서
                yf_key = DART_TO_YF_INCOME.get(account_nm)
                if yf_key:
                    income_rows.setdefault(yf_key, {})[col_ts] = amount
            elif sj_div == "BS":  # 재무상태표
                yf_key = DART_TO_YF_BALANCE.get(account_nm)
                if yf_key:
                    balance_rows.setdefault(yf_key, {})[col_ts] = amount
            elif sj_div == "CF":  # 현금흐름표
                yf_key = DART_TO_YF_CASHFLOW.get(account_nm)
                if yf_key:
                    cashflow_rows.setdefault(yf_key, {})[col_ts] = amount

    return {
        "income":   _build_yf_df(income_rows, columns),
        "balance":  _build_yf_df(balance_rows, columns),
        "cashflow": _build_yf_df(cashflow_rows, columns),
    }


def _fetch_quarterly_financials(dart, code: str, verbose: bool = False) -> dict:
    """
    최근 8분기 재무제표를 수집해 yfinance 형식 DataFrame으로 정규화.

    DART 보고서 코드:
      11013 = 1분기, 11012 = 반기, 11014 = 3분기, 11011 = 사업보고서(연간)

    주의: 반기/3분기/연간은 누적이므로, 단일 분기 매출/이익을 얻으려면
    누적 - 이전누적 = 단일분기 로 빼는 로직 필요. MVP는 누적값으로 일단 둠.
    """
    from datetime import datetime
    from config import DART_REPORT_CODES

    current_year = datetime.now().year
    income_rows = {}
    balance_rows = {}
    cashflow_rows = {}
    columns = []

    # 최근 2~3년치 분기 (간단히 최근 8개 분기)
    quarter_specs = []  # (year, report_code, end_month)
    for year_offset in range(0, 3):
        year = current_year - year_offset
        quarter_specs.extend([
            (year, "11013", 3),    # Q1
            (year, "11012", 6),    # 반기
            (year, "11014", 9),    # 3Q 누적
            (year, "11011", 12),   # 연간
        ])

    quarter_specs = sorted(quarter_specs)  # 시간순 정렬

    fetched_count = 0
    MAX_QUARTERS = 8

    for year, report_code, end_month in quarter_specs:
        if fetched_count >= MAX_QUARTERS:
            break
        try:
            fs = dart.finstate_all(code, year, reprt_code=report_code,
                                   fs_div=DART_DEFAULT_FS_DIV)
        except Exception:
            continue
        if fs is None or fs.empty:
            continue

        col_ts = pd.Timestamp(f"{year}-{end_month:02d}-30")
        columns.append(col_ts)
        fetched_count += 1

        for _, row in fs.iterrows():
            account_nm = row.get("account_nm", "")
            try:
                amount = float(str(row.get("thstrm_amount", "0")).replace(",", ""))
            except (ValueError, TypeError):
                amount = None

            sj_div = row.get("sj_div", "")

            if sj_div in ("IS", "CIS"):
                yf_key = DART_TO_YF_INCOME.get(account_nm)
                if yf_key:
                    income_rows.setdefault(yf_key, {})[col_ts] = amount
            elif sj_div == "BS":
                yf_key = DART_TO_YF_BALANCE.get(account_nm)
                if yf_key:
                    balance_rows.setdefault(yf_key, {})[col_ts] = amount
            elif sj_div == "CF":
                yf_key = DART_TO_YF_CASHFLOW.get(account_nm)
                if yf_key:
                    cashflow_rows.setdefault(yf_key, {})[col_ts] = amount

    return {
        "income":   _build_yf_df(income_rows, columns),
        "balance":  _build_yf_df(balance_rows, columns),
        "cashflow": _build_yf_df(cashflow_rows, columns),
    }


def _build_yf_df(rows: dict, columns: list) -> pd.DataFrame:
    """
    {항목명: {Timestamp: 값}} dict → yfinance 형식 DataFrame.

    yfinance는 행 = 항목, 열 = 날짜 (최신 → 오래된 순).
    """
    if not rows or not columns:
        return pd.DataFrame()

    # 중복 제거하고 최신순 정렬
    unique_cols = sorted(set(columns), reverse=True)

    df = pd.DataFrame(index=list(rows.keys()), columns=unique_cols)
    for row_name, col_values in rows.items():
        for col_ts, value in col_values.items():
            if col_ts in df.columns:
                df.at[row_name, col_ts] = value

    return df.astype(float, errors="ignore")
