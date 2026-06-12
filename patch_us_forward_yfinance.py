"""
patch_us_forward_yfinance.py — Phase 4.5: 미국 forward consensus 1단계.

modules/data_sources/yfinance_source.py에 fetch_us_forward_consensus() 함수 추가.

실행:
    python patch_us_forward_yfinance.py

추가 후 본인 확인 명령:
    python -c "from modules.data_sources.yfinance_source import fetch_us_forward_consensus; \
import json; print(json.dumps(fetch_us_forward_consensus('AAPL', verbose=True), default=str, indent=2))"

안전장치:
    - 백업 자동 생성 (yfinance_source.py.bak.us_forward)
    - 이미 패치되어 있으면 skip (멱등성)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

SRC = Path("modules/data_sources/yfinance_source.py")
BACKUP = Path("modules/data_sources/yfinance_source.py.bak.us_forward")


# ============================================================
# 추가할 함수 (yfinance_source.py 끝에 append)
# ============================================================
NEW_FUNCTION = '''

def fetch_us_forward_consensus(ticker: str, verbose: bool = False) -> dict:
    """
    yfinance Yahoo Finance에서 미국 종목 forward consensus 추출.

    데이터 소스:
        - yf_ticker.earnings_estimate  : 분기/연간 EPS 추정치
        - yf_ticker.revenue_estimate   : 분기/연간 매출 추정치

    각 DataFrame index에 '0q', '+1q', '0y', '+1y' 키가 있음.
    columns: avg, low, high, yearAgo, numberOfAnalysts, growth

    Returns:
        {
            "quarterly_forward": [
                {
                    "period_label": "2026Q2",
                    "period_end":   pd.Timestamp(2026-06-30),
                    "revenue_est":  float (USD),
                    "eps_est":      float (USD),
                    "revenue_yoy":  float (0.159 = +15.9%),
                    "eps_yoy":      float,
                    "n_analysts":   int,
                },
                ...  # 보통 2개 (0q, +1q)
            ],
            "annual_forward": [
                ...  # 보통 2개 (0y, +1y)
            ]
        }
        실패 시 {"quarterly_forward": [], "annual_forward": []}.
    """
    yf_ticker = yf.Ticker(ticker)

    # ---------- earnings_estimate ----------
    try:
        ee_df = yf_ticker.earnings_estimate
        if not isinstance(ee_df, pd.DataFrame) or ee_df.empty:
            ee_df = pd.DataFrame()
    except Exception as e:
        if verbose:
            print(f"  [WARN] earnings_estimate failed for {ticker}: {e}")
        ee_df = pd.DataFrame()

    # ---------- revenue_estimate ----------
    try:
        re_df = yf_ticker.revenue_estimate
        if not isinstance(re_df, pd.DataFrame) or re_df.empty:
            re_df = pd.DataFrame()
    except Exception as e:
        if verbose:
            print(f"  [WARN] revenue_estimate failed for {ticker}: {e}")
        re_df = pd.DataFrame()

    if ee_df.empty and re_df.empty:
        if verbose:
            print(f"  [yf_consensus] {ticker}: no forward data available")
        return {"quarterly_forward": [], "annual_forward": []}

    # ---------- 분기/연도 마감일 추정 ----------
    # 가장 최근 분기/연도 마감일을 base로 잡고 +N 분기/연도
    try:
        q_inc = yf_ticker.quarterly_income_stmt
        last_q_end = (
            pd.Timestamp(q_inc.columns[0])
            if isinstance(q_inc, pd.DataFrame) and not q_inc.empty
            else pd.Timestamp.now().to_period("Q").end_time.normalize()
        )
    except Exception:
        last_q_end = pd.Timestamp.now().to_period("Q").end_time.normalize()

    try:
        a_inc = yf_ticker.income_stmt
        last_y_end = (
            pd.Timestamp(a_inc.columns[0])
            if isinstance(a_inc, pd.DataFrame) and not a_inc.empty
            else pd.Timestamp(year=pd.Timestamp.now().year - 1, month=12, day=31)
        )
    except Exception:
        last_y_end = pd.Timestamp(year=pd.Timestamp.now().year - 1, month=12, day=31)

    def _calc_q_end(offset_q: int) -> pd.Timestamp:
        period = last_q_end.to_period("Q") + offset_q
        return period.end_time.normalize()

    def _calc_y_end(offset_y: int) -> pd.Timestamp:
        return (last_y_end + pd.DateOffset(years=offset_y)).normalize()

    # ---------- 안전 추출 헬퍼 ----------
    def _safe_get(df: pd.DataFrame, row_key: str, col: str):
        if df.empty or row_key not in df.index or col not in df.columns:
            return None
        val = df.loc[row_key, col]
        try:
            if pd.isna(val):
                return None
        except (TypeError, ValueError):
            return None
        return float(val)

    def _row_exists(df: pd.DataFrame, row_key: str) -> bool:
        return not df.empty and row_key in df.index

    # ---------- 분기 forward ----------
    quarterly_forward = []
    for offset, key in enumerate(["0q", "+1q"]):
        if not _row_exists(ee_df, key) and not _row_exists(re_df, key):
            continue

        eps_est    = _safe_get(ee_df, key, "avg")
        eps_growth = _safe_get(ee_df, key, "growth")
        rev_est    = _safe_get(re_df, key, "avg")
        rev_growth = _safe_get(re_df, key, "growth")
        n_analysts = (_safe_get(ee_df, key, "numberOfAnalysts")
                      or _safe_get(re_df, key, "numberOfAnalysts"))

        if eps_est is None and rev_est is None:
            continue

        # 0q는 다음 분기 마감(+1), +1q는 그 다음(+2)
        q_end = _calc_q_end(offset + 1)
        quarter_label = f"{q_end.year}Q{q_end.quarter}"

        quarterly_forward.append({
            "period_label": quarter_label,
            "period_end":   q_end,
            "revenue_est":  rev_est,
            "eps_est":      eps_est,
            "revenue_yoy":  rev_growth,
            "eps_yoy":      eps_growth,
            "n_analysts":   int(n_analysts) if n_analysts else None,
        })

    # ---------- 연간 forward ----------
    annual_forward = []
    for offset, key in enumerate(["0y", "+1y"]):
        if not _row_exists(ee_df, key) and not _row_exists(re_df, key):
            continue

        eps_est    = _safe_get(ee_df, key, "avg")
        eps_growth = _safe_get(ee_df, key, "growth")
        rev_est    = _safe_get(re_df, key, "avg")
        rev_growth = _safe_get(re_df, key, "growth")
        n_analysts = (_safe_get(ee_df, key, "numberOfAnalysts")
                      or _safe_get(re_df, key, "numberOfAnalysts"))

        if eps_est is None and rev_est is None:
            continue

        y_end = _calc_y_end(offset + 1)
        year_label = f"FY{y_end.year}"

        annual_forward.append({
            "period_label": year_label,
            "period_end":   y_end,
            "revenue_est":  rev_est,
            "eps_est":      eps_est,
            "revenue_yoy":  rev_growth,
            "eps_yoy":      eps_growth,
            "n_analysts":   int(n_analysts) if n_analysts else None,
        })

    if verbose:
        print(f"  [yf_consensus] {ticker}: "
              f"{len(quarterly_forward)} quarters + {len(annual_forward)} years")

    return {
        "quarterly_forward": quarterly_forward,
        "annual_forward":    annual_forward,
    }
'''


def main() -> int:
    if not SRC.exists():
        print(f"✗ {SRC} 없음.")
        print("  investment_analysis_tool/ 디렉토리에서 실행하세요.")
        return 1

    text = SRC.read_text()

    if "def fetch_us_forward_consensus" in text:
        print("✓ 이미 패치됨 — 함수 fetch_us_forward_consensus 존재")
        return 0

    if not BACKUP.exists():
        shutil.copy(SRC, BACKUP)
        print(f"✓ 백업 생성: {BACKUP}")

    # 파일 끝에 새 함수 append
    if not text.endswith("\n"):
        text += "\n"
    text += NEW_FUNCTION

    SRC.write_text(text)
    print(f"✓ {SRC}에 fetch_us_forward_consensus() 추가됨")
    print()
    print("동작 확인 명령:")
    print('  python -c "from modules.data_sources.yfinance_source import fetch_us_forward_consensus; \\')
    print('import json; print(json.dumps(fetch_us_forward_consensus(\'AAPL\', verbose=True), default=str, indent=2))"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
