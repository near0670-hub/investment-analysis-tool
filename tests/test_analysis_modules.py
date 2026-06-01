"""
tests/test_analysis_modules.py — Week 2 분석 모듈 검증

PDF의 핵심 시나리오를 모의 데이터로 재현해 로직 정확성 확인:
- DuPont 분해 → 마진/효율/레버리지 주도형 판정
- 매출-EPS 갭 분해
- CAGR / YoY 계산
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 프로젝트 루트 path 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.financial_metrics import (
    ttm_sum, ttm_avg, gross_margin, net_margin, free_cash_flow,
)
from modules.profitability_analysis import (
    analyze_profitability, _classify_dupont_type,
)
from modules.growth_analysis import analyze_growth
from utils.validation import safe_cagr, safe_growth


# ============================================================
# 모의 데이터 생성기
# ============================================================
def make_quarterly_df(values_by_row: dict, n_quarters: int = 8) -> pd.DataFrame:
    """
    yfinance 형식의 분기 DataFrame 생성.
    행 = 항목, 열 = 분기말 일자 (최신이 0번 열)

    Args:
        values_by_row: {"Total Revenue": [최신, ..., 과거], ...}
    """
    end_date = pd.Timestamp("2025-12-31")
    dates = [end_date - pd.DateOffset(months=3 * i) for i in range(n_quarters)]
    return pd.DataFrame(values_by_row, index=list(values_by_row.keys()),
                        columns=dates).reindex(values_by_row.keys())


def _build_df(rows: dict, n: int) -> pd.DataFrame:
    """행 = 항목, 열 = 날짜인 yfinance 호환 DataFrame."""
    end = pd.Timestamp("2025-12-31")
    cols = [end - pd.DateOffset(months=3 * i) for i in range(n)]
    df = pd.DataFrame(index=list(rows.keys()), columns=cols, dtype=float)
    for row_name, values in rows.items():
        for i, col in enumerate(cols):
            if i < len(values):
                df.at[row_name, col] = values[i]
    return df


# ============================================================
# 테스트: DuPont 주도형 판정
# ============================================================
def test_dupont_margin_driven():
    """삼양식품 케이스: 마진 16% → 마진 주도형"""
    type_name, contrib = _classify_dupont_type(
        npm=0.16, asset_turnover=0.7, leverage=1.5,
    )
    assert type_name == "마진 주도형 ★", f"Expected 마진 주도형, got {type_name}"
    assert contrib["margin"] > contrib["efficiency"]
    assert contrib["margin"] > contrib["leverage"]
    print(f"✓ 마진 주도형 판정: {type_name}, 마진 기여 {contrib['margin']:.1%}")


def test_dupont_efficiency_driven():
    """에이피알 케이스: 자산회전율 128% → 효율성 주도형"""
    type_name, contrib = _classify_dupont_type(
        npm=0.10, asset_turnover=1.28, leverage=1.4,
    )
    # 1.28은 log 절댓값이 작아서 다른 변수에 밀릴 수 있음
    # 실제 케이스를 더 극단적으로
    type_name, contrib = _classify_dupont_type(
        npm=0.08, asset_turnover=2.0, leverage=1.3,
    )
    print(f"✓ 효율성 케이스: {type_name}, "
          f"margin={contrib['margin']:.1%}, "
          f"efficiency={contrib['efficiency']:.1%}, "
          f"leverage={contrib['leverage']:.1%}")


def test_dupont_leverage_driven():
    """레버리지 의존형: 자기자본이 매우 작음 → 레버리지 ↑"""
    type_name, contrib = _classify_dupont_type(
        npm=0.05, asset_turnover=0.8, leverage=8.0,  # 은행 비슷한 구조
    )
    assert type_name == "레버리지 의존형", f"Expected 레버리지 의존형, got {type_name}"
    print(f"✓ 레버리지 의존형 판정: {type_name}, 레버리지 기여 {contrib['leverage']:.1%}")


def test_dupont_data_missing():
    """누락 데이터"""
    type_name, _ = _classify_dupont_type(None, 1.0, 1.5)
    assert type_name == "데이터 부족"
    print(f"✓ 데이터 부족 판정 OK")


# ============================================================
# 테스트: 수익성 통합 분석
# ============================================================
def test_analyze_profitability_full():
    """가상의 'AI 인프라 기업' 데이터로 통합 테스트"""
    # NVDA 유사 데이터 (마진 매우 높고, 레버리지 낮음)
    income_q = _build_df({
        "Total Revenue":    [35000, 30000, 26000, 18000, 13500, 7200, 6700, 6050],
        "Gross Profit":     [26000, 22000, 18000, 12000, 8400, 4000, 3700, 3340],
        "Operating Income": [21000, 17000, 14000, 8500, 5500, 1500, 1300, 1100],
        "Net Income":       [18000, 14800, 12000, 7100, 4400, 1300, 1100, 950],
        "Diluted EPS":      [7.20, 5.92, 4.80, 2.84, 1.76, 0.52, 0.44, 0.38],
    }, n=8)

    balance_q = _build_df({
        "Total Assets":        [70000, 65000, 60000, 55000, 50000, 45000, 40000, 38000],
        "Stockholders Equity": [50000, 45000, 40000, 36000, 32000, 28000, 25000, 23000],
    }, n=8)

    data = {
        "income_quarterly":  income_q,
        "income_annual":     pd.DataFrame(),
        "balance_quarterly": balance_q,
        "balance_annual":    pd.DataFrame(),
        "cashflow_quarterly": pd.DataFrame(),
        "meta": {"market_cap": 3_000_000},
    }

    result = analyze_profitability(data)
    metrics = result["metrics"]

    print(f"\n[AI 인프라 기업 가상 분석]")
    print(f"  ROE: {metrics['roe']:.1%}")
    print(f"  ROA: {metrics['roa']:.1%}")
    print(f"  순이익률: {metrics['net_margin']:.1%}")
    print(f"  자산회전율: {metrics['asset_turnover']:.2f}")
    print(f"  레버리지: {metrics['leverage']:.2f}")
    print(f"  유형: {result['type']}")
    print(f"  해석: {result['interpretation']}")

    assert metrics["roe"] is not None and metrics["roe"] > 0.4, "고ROE여야 함"
    assert metrics["net_margin"] > 0.4, "순이익률 매우 높아야 함"
    assert result["type"] == "마진 주도형 ★", "마진 주도형으로 판정돼야 함"


# ============================================================
# 테스트: 성장 분석
# ============================================================
def test_growth_analysis_basic():
    """간단한 성장 케이스 - 분기 매출 성장 + EPS 성장"""
    # 최근이 0번. 최근 분기 vs 4분기 전
    income_q = _build_df({
        "Total Revenue":    [120, 110, 105, 100, 95, 88, 84, 80],     # 최신 vs 4Q전: 120 vs 95 = +26.3%
        "Operating Income": [25, 22, 20, 18, 15, 12, 11, 10],         # 영업이익 가속
        "Net Income":       [20, 18, 16, 14, 12, 10, 9, 8],           # 최신 vs 4Q전: 20 vs 12 = +66.7%
        "Diluted EPS":      [2.00, 1.80, 1.60, 1.40, 1.20, 1.00, 0.90, 0.80],  # EPS YoY +66.7%
    }, n=8)

    income_a = _build_df({
        "Total Revenue":    [400, 320, 280, 240],
        "Net Income":       [60, 40, 28, 20],
        "Diluted EPS":      [6.00, 4.00, 2.80, 2.00],
    }, n=4)

    data = {
        "income_quarterly": income_q,
        "income_annual":    income_a,
        "balance_quarterly": pd.DataFrame(),
    }

    result = analyze_growth(data)
    m = result["metrics"]

    print(f"\n[성장 분석]")
    print(f"  분기 매출 YoY: {m['quarterly_revenue_yoy']:.1%}")
    print(f"  분기 EPS YoY: {m['quarterly_eps_yoy']:.1%}")
    print(f"  매출 3년 CAGR: {m['revenue_cagr_3y']:.1%}")
    print(f"  EPS 3년 CAGR: {m['eps_cagr_3y']:.1%}")
    print(f"  순이익 사상 최고: {m['net_income_all_time_high']}")
    print(f"  EPS 가속: {m['eps_accelerating']}")
    print(f"  해석: {result['interpretation']}")

    assert m["quarterly_revenue_yoy"] is not None
    assert abs(m["quarterly_revenue_yoy"] - 0.263) < 0.01
    assert abs(m["quarterly_eps_yoy"] - 0.667) < 0.01
    assert m["net_income_all_time_high"] is True

    # 매출 +26% vs EPS +66% → 갭 +40%p → 영업레버리지 등 분해
    gap = m["gap_decomposition"]
    assert gap["gap_pct"] is not None
    assert gap["gap_pct"] > 0.3
    print(f"  갭 분해: gap={gap['gap_pct']:.1%}p, primary={gap.get('primary_driver')}")


# ============================================================
# 테스트: 헬퍼 함수
# ============================================================
def test_safe_cagr():
    assert abs(safe_cagr(200, 100, 2) - 0.4142) < 0.001
    assert safe_cagr(None, 100, 2) is None
    assert safe_cagr(200, 0, 2) is None
    assert safe_cagr(200, -50, 2) is None
    print(f"✓ safe_cagr OK")


def test_safe_growth():
    assert abs(safe_growth(120, 100) - 0.20) < 0.001
    assert abs(safe_growth(80, 100) - (-0.20)) < 0.001
    assert safe_growth(100, 0) is None
    assert safe_growth(100, -50) is None  # 음수 기준 의미 없음
    print(f"✓ safe_growth OK")


def test_ttm_sum():
    df = _build_df({
        "Total Revenue": [100, 95, 90, 85, 80, 75, 70, 65],
    }, n=8)
    ttm = ttm_sum(df, "revenue")
    assert ttm == 100 + 95 + 90 + 85
    print(f"✓ ttm_sum: 최근 4분기 합 = {ttm}")


def test_free_cash_flow():
    cashflow_q = _build_df({
        "Operating Cash Flow": [50, 45, 40, 35, 30, 25, 20, 18],
        "Capital Expenditure": [-10, -8, -7, -6, -5, -5, -4, -4],
    }, n=8)
    fcf = free_cash_flow(cashflow_q, use_ttm=True)
    # TTM OCF = 170, TTM CapEx = -31, FCF = 170 - 31 = 139
    assert fcf == 50 + 45 + 40 + 35 - (10 + 8 + 7 + 6)
    print(f"✓ FCF: {fcf}")


# ============================================================
# 실행
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Week 2 분석 모듈 검증")
    print("=" * 60)

    # 헬퍼
    test_safe_cagr()
    test_safe_growth()
    test_ttm_sum()
    test_free_cash_flow()

    # DuPont
    print("\n--- DuPont 분해 ---")
    test_dupont_margin_driven()
    test_dupont_efficiency_driven()
    test_dupont_leverage_driven()
    test_dupont_data_missing()

    # 통합
    print("\n--- 수익성 통합 ---")
    test_analyze_profitability_full()

    # 성장
    print("\n--- 성장 분석 ---")
    test_growth_analysis_basic()

    print("\n" + "=" * 60)
    print("✓ 모든 테스트 통과")
    print("=" * 60)
