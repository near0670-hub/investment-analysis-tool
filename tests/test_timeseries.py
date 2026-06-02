"""
tests/test_timeseries.py — 시계열 추출 검증

핵심 시나리오:
1. 분기 시계열 (과거 4분기, 미래 0)
2. 분기 시계열 + 사용자 미래 EPS 입력 (Q+1, Q+2)
3. 연간 시계열 (과거 4년)
4. 연간 시계열 + yfinance forwardEps
5. 빈 데이터 처리
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.timeseries import extract_timeseries


def _build_quarter_df(rows: dict, n_quarters: int) -> pd.DataFrame:
    end = pd.Timestamp("2025-12-31")
    cols = [end - pd.DateOffset(months=3 * i) for i in range(n_quarters)]
    df = pd.DataFrame(index=list(rows.keys()), columns=cols, dtype=float)
    for row_name, values in rows.items():
        for i, col in enumerate(cols):
            if i < len(values):
                df.at[row_name, col] = values[i]
    return df


def _build_annual_df(rows: dict, n_years: int) -> pd.DataFrame:
    end = pd.Timestamp("2025-12-31")
    cols = [end - pd.DateOffset(years=i) for i in range(n_years)]
    df = pd.DataFrame(index=list(rows.keys()), columns=cols, dtype=float)
    for row_name, values in rows.items():
        for i, col in enumerate(cols):
            if i < len(values):
                df.at[row_name, col] = values[i]
    return df


# ============================================================
# 1. 분기 시계열 (과거만)
# ============================================================
def test_quarterly_history_only():
    income_q = _build_quarter_df({
        "Total Revenue": [120, 110, 100, 90, 80, 75, 70, 65],
        "Diluted EPS":   [3.0, 2.8, 2.5, 2.2, 2.0, 1.9, 1.8, 1.7],
    }, n_quarters=8)  # 8개 중 4개만 history로 잡힘

    data = {
        "income_quarterly": income_q,
        "income_annual": pd.DataFrame(),
        "balance_annual": pd.DataFrame(),
        "info": {},
        "meta": {"currency": "USD"},
    }

    ts = extract_timeseries(data, n_quarters_history=4, n_years_history=4)
    q = ts["quarterly"]

    assert not q.empty
    assert len(q) == 4  # 과거 4분기만 (미래 입력 없음)
    # 정렬 검증: 과거 → 최신
    assert q.iloc[0]["period"] < q.iloc[-1]["period"]
    # 최신 분기 (가장 큰 값)
    assert q.iloc[-1]["eps"] == 3.0
    # YoY: 최신 EPS (3.0) vs 4분기 전 (2.0) → +50%
    last_yoy = q.iloc[-1]["eps_yoy"]
    assert abs(last_yoy - 0.50) < 0.01, f"Expected +50%, got {last_yoy}"
    # is_future 모두 False
    assert not q["is_future"].any()
    print(f"✓ 분기 시계열 (과거만): 4개 행, EPS YoY 최신 = {last_yoy:+.1%}")


# ============================================================
# 2. 분기 시계열 + 사용자 미래 EPS 입력
# ============================================================
def test_quarterly_with_user_future():
    income_q = _build_quarter_df({
        "Total Revenue": [120, 110, 100, 90, 80, 75, 70, 65],
        "Diluted EPS":   [3.0, 2.8, 2.5, 2.2, 2.0, 1.9, 1.8, 1.7],
    }, n_quarters=8)

    data = {
        "income_quarterly": income_q,
        "income_annual": pd.DataFrame(),
        "balance_annual": pd.DataFrame(),
        "info": {},
        "meta": {"currency": "USD"},
    }

    # 사용자가 Q+1=3.5, Q+2=4.0 입력
    ts = extract_timeseries(
        data,
        n_quarters_history=4,
        user_quarterly_eps=[3.5, 4.0],
    )
    q = ts["quarterly"]

    # 4 (과거) + 2 (미래) = 6
    assert len(q) == 6, f"Expected 6 rows, got {len(q)}"

    # 미래 2개의 is_future = True
    future = q[q["is_future"]]
    assert len(future) == 2
    assert future.iloc[0]["eps"] == 3.5
    assert future.iloc[1]["eps"] == 4.0
    assert future.iloc[0]["source"] == "user_input"

    # 미래 분기 라벨이 마지막 실제 분기 다음인지
    assert "2026" in future.iloc[0]["period"]

    # YoY: Q+1=3.5 vs 1년 전 (2025.03 데이터 = 2.2) → +59%
    yoy_q1 = future.iloc[0]["eps_yoy"]
    assert abs(yoy_q1 - 0.59) < 0.05, f"Expected ~+59%, got {yoy_q1}"

    print(f"✓ 분기 시계열 + 사용자 미래: 6개 행 (4과거+2미래), Q+1 YoY = {yoy_q1:+.1%}")


# ============================================================
# 3. 연간 시계열 (과거 + yfinance forwardEps)
# ============================================================
def test_annual_with_forward_eps():
    income_a = _build_annual_df({
        "Total Revenue": [12000, 11000, 9500, 8000],
        "Diluted EPS":   [12.0, 10.0, 8.0, 6.5],
        "Net Income":    [4000, 3500, 3000, 2500],
    }, n_years=4)
    balance_a = _build_annual_df({
        "Stockholders Equity": [25000, 22000, 19000, 16000],
    }, n_years=4)

    data = {
        "income_quarterly": pd.DataFrame(),
        "income_annual": income_a,
        "balance_annual": balance_a,
        "info": {"forwardEps": 15.0},  # yfinance가 제공하는 NTM EPS
        "meta": {"currency": "USD"},
    }

    ts = extract_timeseries(data, n_years_history=4)
    a = ts["annual"]

    # 4 (과거) + 1 (yfinance forward) = 5 (사용자 입력 없음, 2년차 없음)
    assert len(a) == 5, f"Expected 5 rows, got {len(a)}"

    # ROE 계산 확인 (최신: 4000/25000 = 16%)
    last_actual = a[~a["is_future"]].iloc[-1]
    assert abs(last_actual["roe"] - 0.16) < 0.01

    # forward 행
    future = a[a["is_future"]]
    assert len(future) == 1
    assert future.iloc[0]["eps"] == 15.0
    assert future.iloc[0]["source"] == "consensus"

    print(f"✓ 연간 시계열 + forwardEps: 5개 행, 최신 ROE = {last_actual['roe']:.1%}")


# ============================================================
# 4. 연간 시계열 + 사용자 입력 (1Y, 2Y 둘 다)
# ============================================================
def test_annual_with_user_input():
    income_a = _build_annual_df({
        "Total Revenue": [12000, 11000, 9500, 8000],
        "Diluted EPS":   [12.0, 10.0, 8.0, 6.5],
    }, n_years=4)

    data = {
        "income_quarterly": pd.DataFrame(),
        "income_annual": income_a,
        "balance_annual": pd.DataFrame(),
        "info": {"forwardEps": 15.0},
        "meta": {"currency": "USD"},
    }

    # 사용자가 FY+1=14, FY+2=17 입력 (forwardEps 무시되고 사용자 입력 우선)
    ts = extract_timeseries(
        data,
        n_years_history=4,
        user_annual_eps=[14.0, 17.0],
    )
    a = ts["annual"]

    future = a[a["is_future"]]
    assert len(future) == 2
    assert future.iloc[0]["eps"] == 14.0  # 사용자 입력 우선
    assert future.iloc[0]["source"] == "user_input"
    assert future.iloc[1]["eps"] == 17.0

    # YoY: FY+1=14 vs FY=12 → +16.7%
    yoy_1y = future.iloc[0]["eps_yoy"]
    assert abs(yoy_1y - 0.1667) < 0.01

    print(f"✓ 연간 + 사용자 입력 2개: FY+1 YoY = {yoy_1y:+.1%}, FY+2 EPS = {future.iloc[1]['eps']}")


# ============================================================
# 5. 빈 데이터 처리
# ============================================================
def test_empty_data():
    data = {
        "income_quarterly": pd.DataFrame(),
        "income_annual": pd.DataFrame(),
        "balance_annual": pd.DataFrame(),
        "info": {},
        "meta": {},
    }

    ts = extract_timeseries(data)
    assert ts["quarterly"].empty
    assert ts["annual"].empty
    print("✓ 빈 데이터: 정상 처리 (DataFrame empty)")


# ============================================================
# 실행
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Timeseries 검증")
    print("=" * 60)

    test_quarterly_history_only()
    test_quarterly_with_user_future()
    test_annual_with_forward_eps()
    test_annual_with_user_input()
    test_empty_data()

    print("=" * 60)
    print("✓ 모든 시계열 테스트 통과")
    print("=" * 60)
