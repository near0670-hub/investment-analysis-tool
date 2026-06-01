"""
tests/test_data_loader.py — 데이터 로더 핵심 로직 검증

특히 _merge_financial_statements의 분기 매칭 + NaN 채우기 로직 검증.
이게 정확해야 PEG/DuPont이 정확해짐.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 프로젝트 루트 path 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.data_loader import _merge_financial_statements


def _build_df(rows: dict, dates: list) -> pd.DataFrame:
    """행=항목, 열=분기말일자 형식의 DataFrame 생성."""
    df = pd.DataFrame(index=list(rows.keys()), columns=dates, dtype=float)
    for row_name, values in rows.items():
        for i, date in enumerate(dates):
            if i < len(values):
                df.at[row_name, date] = values[i]
    return df


# ============================================================
# 테스트 1: 둘 다 비어있으면 빈 결과
# ============================================================
def test_both_empty():
    result = _merge_financial_statements(pd.DataFrame(), pd.DataFrame())
    assert result.empty
    print("✓ test_both_empty")


# ============================================================
# 테스트 2: 한쪽만 있으면 그대로
# ============================================================
def test_only_yfinance():
    yf = _build_df({"Total Revenue": [100, 90, 80]},
                   [pd.Timestamp("2025-12-31"), pd.Timestamp("2025-09-30"),
                    pd.Timestamp("2025-06-30")])
    result = _merge_financial_statements(yf, pd.DataFrame())
    assert len(result.columns) == 3
    assert result.loc["Total Revenue", pd.Timestamp("2025-12-31")] == 100
    print("✓ test_only_yfinance")


def test_only_dart():
    dart = _build_df({"Total Revenue": [110, 95, 85]},
                     [pd.Timestamp("2025-12-31"), pd.Timestamp("2025-09-30"),
                      pd.Timestamp("2025-06-30")])
    result = _merge_financial_statements(pd.DataFrame(), dart)
    assert len(result.columns) == 3
    assert result.loc["Total Revenue", pd.Timestamp("2025-12-31")] == 110
    print("✓ test_only_dart")


# ============================================================
# 테스트 3: ★ 핵심 — 같은 분기 컬럼 통합
# ============================================================
def test_same_quarters_merged():
    """yfinance와 DART의 같은 분기는 한 컬럼으로 합쳐져야 함."""
    yf = _build_df({"Total Revenue": [100, 90]},
                   [pd.Timestamp("2025-12-31"), pd.Timestamp("2025-09-30")])
    dart = _build_df({"Total Revenue": [110, 95]},
                     [pd.Timestamp("2025-12-31"), pd.Timestamp("2025-09-30")])

    result = _merge_financial_statements(yf, dart, prefer="dart")

    # 같은 분기는 한 컬럼으로 → 컬럼 2개여야 함 (4개 X)
    assert len(result.columns) == 2, f"Expected 2 columns, got {len(result.columns)}"

    # DART 값이 우선되어야 함
    assert result.loc["Total Revenue", pd.Timestamp("2025-12-31")] == 110
    print(f"✓ test_same_quarters_merged: 2개 분기로 통합, DART 우선")


# ============================================================
# 테스트 4: 분기 날짜가 살짝 다른 경우 (±15일 이내)
# ============================================================
def test_close_dates_matched():
    """yfinance 12/31, DART 12/30 같은 미세 차이는 같은 분기로."""
    yf = _build_df({"Total Revenue": [100]}, [pd.Timestamp("2025-12-31")])
    dart = _build_df({"Total Revenue": [110]}, [pd.Timestamp("2025-12-30")])

    result = _merge_financial_statements(yf, dart, prefer="dart")

    # 컬럼은 1개 (둘이 같은 분기로 매칭됨)
    assert len(result.columns) == 1, f"Expected 1 column, got {len(result.columns)}"
    # 매칭된 컬럼은 DART 날짜
    assert pd.Timestamp("2025-12-30") in result.columns
    # 값은 DART 우선
    assert result.loc["Total Revenue", pd.Timestamp("2025-12-30")] == 110
    print("✓ test_close_dates_matched: ±15일 매칭")


# ============================================================
# 테스트 5: ★ 핵심 — NaN 채우기
# ============================================================
def test_nan_filling():
    """
    DART에 없는 항목(예: EBITDA)이 yfinance에 있으면 같은 분기에서 채워줘야 함.
    Q4: DART에 매출/영업이익만, yfinance에 매출/영업이익/EBITDA 다 있음
    → 결과: Q4에 매출=DART값, 영업이익=DART값, EBITDA=yfinance값
    """
    yf = _build_df({
        "Total Revenue":    [100],
        "Operating Income": [25],
        "EBITDA":           [30],
    }, [pd.Timestamp("2025-12-31")])

    dart = _build_df({
        "Total Revenue":    [110],
        "Operating Income": [28],
        # EBITDA는 없음
    }, [pd.Timestamp("2025-12-31")])

    result = _merge_financial_statements(yf, dart, prefer="dart")

    # 컬럼 1개
    assert len(result.columns) == 1
    col = result.columns[0]

    # 매출/영업이익은 DART
    assert result.loc["Total Revenue", col] == 110
    assert result.loc["Operating Income", col] == 28
    # EBITDA는 yfinance (DART에 없어서 자동 fill)
    assert result.loc["EBITDA", col] == 30, "EBITDA가 yfinance로 fill 되어야 함"
    print("✓ test_nan_filling: DART에 없는 EBITDA가 yfinance 값으로 채워짐")


# ============================================================
# 테스트 6: 같은 항목, 한쪽 NaN → 다른 쪽 값으로 채워짐
# ============================================================
def test_partial_nan_filling():
    """
    DART Q3 매출은 NaN, yfinance Q3 매출은 90 → 결과 Q3 매출 = 90
    """
    yf = _build_df({"Total Revenue": [100, 90]},
                   [pd.Timestamp("2025-12-31"), pd.Timestamp("2025-09-30")])

    dart = _build_df({"Total Revenue": [110, None]},  # Q3 NaN
                     [pd.Timestamp("2025-12-31"), pd.Timestamp("2025-09-30")])

    result = _merge_financial_statements(yf, dart, prefer="dart")

    # Q4는 DART 우선
    assert result.loc["Total Revenue", pd.Timestamp("2025-12-31")] == 110
    # Q3는 DART가 NaN이라 yfinance 값으로 fill
    assert result.loc["Total Revenue", pd.Timestamp("2025-09-30")] == 90
    print("✓ test_partial_nan_filling: 부분 NaN도 채워짐")


# ============================================================
# 테스트 7: 한쪽에만 있는 분기는 그대로 유지
# ============================================================
def test_unmatched_quarter_preserved():
    """
    DART에는 Q4만, yfinance에는 Q4 + Q3 → 결과는 Q4 + Q3 둘 다 컬럼으로 유지
    """
    yf = _build_df({"Total Revenue": [100, 90]},
                   [pd.Timestamp("2025-12-31"), pd.Timestamp("2025-09-30")])

    dart = _build_df({"Total Revenue": [110]},
                     [pd.Timestamp("2025-12-31")])

    result = _merge_financial_statements(yf, dart, prefer="dart")

    # 컬럼 2개 (Q4 + Q3)
    assert len(result.columns) == 2
    # Q4는 DART
    assert result.loc["Total Revenue", pd.Timestamp("2025-12-31")] == 110
    # Q3는 yfinance만 있는 분기 → 그 값 유지
    assert result.loc["Total Revenue", pd.Timestamp("2025-09-30")] == 90
    print("✓ test_unmatched_quarter_preserved: 매칭 안 된 분기도 유지")


# ============================================================
# 실행
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("data_loader._merge_financial_statements 검증")
    print("=" * 60)

    test_both_empty()
    test_only_yfinance()
    test_only_dart()
    test_same_quarters_merged()
    test_close_dates_matched()
    test_nan_filling()
    test_partial_nan_filling()
    test_unmatched_quarter_preserved()

    print("=" * 60)
    print("✓ 모든 데이터 로더 테스트 통과")
    print("=" * 60)
