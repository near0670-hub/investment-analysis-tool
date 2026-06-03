"""
tests/test_valuation_timeseries.py — Valuation 시계열 검증

시나리오:
1. Re-rating opportunity (한국, 가상)
2. Premium territory (한국, 가상)
3. Value trap warning
4. Mean reversion (보통)
5. 미국 종목 (yfinance, 시계열 제한)
6. 빈 데이터
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.valuation_timeseries import calculate_valuation_timeseries, THRESHOLDS


def _make_naver_data(per_series, pbr_series, div_yield_series, future_year=None):
    """네이버 데이터 구조 헬퍼."""
    cols = [pd.Timestamp(f"{2022+i}-12-31") for i in range(len(per_series))]
    annual = pd.DataFrame(
        index=["PER Naver", "PBR Naver", "Dividend Yield", "Total Revenue", "Net Margin", "ROE"],
        columns=cols,
        data=[
            per_series,
            pbr_series,
            div_yield_series,
            [100e12] * len(per_series),
            [10.0] * len(per_series),
            [10.0] * len(per_series),
        ],
    )

    naver_data = {
        "annual": annual,
        "quarterly": pd.DataFrame(),
        "future_periods": [f"{future_year}.12(E)"] if future_year else [],
        "source": "naver",
    }
    return naver_data


# ============================================================
# Test 1: Re-rating opportunity
# ============================================================
def test_rerating_opportunity():
    """
    Scenario: 5Y avg PER = 20x, current = 14x (-30% vs avg)
              + consensus PER 10x → implied growth 40%
    Expected: RE-RATING OPPORTUNITY 시그널
    """
    # PER: 22, 24, 19, 14 (actual, 평균 ~19.75) + 10 (consensus → growth 40%)
    naver_data = _make_naver_data(
        per_series=[22.0, 24.0, 19.0, 14.0, 10.0],
        pbr_series=[2.0, 2.2, 1.9, 1.5, 1.2],
        div_yield_series=[1.5, 1.5, 2.0, 2.5, 3.0],
        future_year=2026,
    )

    data = {
        "meta": {"country": "KR"},
        "kr_naver_consensus": naver_data,
        "info": {},
        "income_quarterly": pd.DataFrame(),
    }

    result = calculate_valuation_timeseries(data, n_history=4)
    assert result is not None, "결과 None"
    assert result["country"] == "KR"

    signals = result["signals"]
    primary = signals[0]
    print(f"  Primary signal: {primary['label']}")
    print(f"  Narrative: {result['narrative']}")
    for e in result["evidence"]:
        print(f"    → {e}")

    # 검증: Re-rating opportunity 매칭
    assert primary["label"] == "RE-RATING OPPORTUNITY", \
        f"Expected RE-RATING, got {primary['label']}"
    assert primary["variant"] == "positive"

    print("✓ Re-rating opportunity 시그널 정확히 분류")


# ============================================================
# Test 2: Premium territory
# ============================================================
def test_premium_territory():
    """
    Scenario: 5Y avg PER = 15x, current = 22x (+47% vs avg)
    Expected: PREMIUM TERRITORY
    """
    naver_data = _make_naver_data(
        per_series=[12.0, 14.0, 15.0, 16.0, 22.0],
        pbr_series=[1.0, 1.2, 1.3, 1.4, 2.0],
        div_yield_series=[3.0, 2.8, 2.5, 2.2, 1.5],
        future_year=None,  # 컨센서스 없음
    )

    data = {
        "meta": {"country": "KR"},
        "kr_naver_consensus": naver_data,
        "info": {},
        "income_quarterly": pd.DataFrame(),
    }

    result = calculate_valuation_timeseries(data, n_history=4)
    assert result is not None

    primary = result["signals"][0]
    print(f"  Primary signal: {primary['label']}")
    print(f"  Narrative: {result['narrative']}")

    # Premium territory 시그널 매칭
    # actual 5개 → 평균 (12+14+15+16+22)/5 = 15.8
    # 22 / 15.8 = 1.39 → +39% > 20% (premium threshold)
    assert primary["label"] == "PREMIUM TERRITORY", \
        f"Expected PREMIUM, got {primary['label']}"

    print("✓ Premium territory 시그널 정확히 분류")


# ============================================================
# Test 3: Mean reversion
# ============================================================
def test_mean_reversion():
    """
    Scenario: 5Y avg PER = 15x, current = 16x (+6% vs avg, within ±10%)
    Expected: NEAR MEAN
    """
    naver_data = _make_naver_data(
        per_series=[14.0, 15.0, 16.0, 15.0, 16.0],
        pbr_series=[1.5] * 5,
        div_yield_series=[2.0] * 5,
        future_year=None,
    )

    data = {
        "meta": {"country": "KR"},
        "kr_naver_consensus": naver_data,
        "info": {},
        "income_quarterly": pd.DataFrame(),
    }

    result = calculate_valuation_timeseries(data)
    primary = result["signals"][0]
    print(f"  Primary signal: {primary['label']}")
    print(f"  Narrative: {result['narrative']}")

    # avg = (14+15+16+15+16)/5 = 15.2, current = 16, deviation = +5.3%
    assert primary["label"] == "NEAR MEAN", \
        f"Expected NEAR MEAN, got {primary['label']}"
    print("✓ Mean reversion 정확히 분류")


# ============================================================
# Test 4: Average metrics 계산 정확성
# ============================================================
def test_average_metrics():
    """
    5Y avg, min, max가 정확히 계산되는지.
    """
    naver_data = _make_naver_data(
        per_series=[10.0, 12.0, 15.0, 18.0, 14.0],  # avg=13.8, min=10, max=18
        pbr_series=[1.0, 1.2, 1.5, 1.8, 1.4],
        div_yield_series=[2.0] * 5,
        future_year=None,
    )

    data = {
        "meta": {"country": "KR"},
        "kr_naver_consensus": naver_data,
        "info": {},
        "income_quarterly": pd.DataFrame(),
    }

    result = calculate_valuation_timeseries(data, n_history=4)
    avg = result["avg_metrics"]

    # actual 5개 평균
    expected_avg = (10 + 12 + 15 + 18 + 14) / 5
    assert abs(avg["per_avg"] - expected_avg) < 0.01, \
        f"avg: expected {expected_avg}, got {avg['per_avg']}"
    assert avg["per_min"] == 10.0
    assert avg["per_max"] == 18.0
    print(f"✓ Average metrics: avg {avg['per_avg']:.2f}, min {avg['per_min']}, max {avg['per_max']}")


# ============================================================
# Test 5: 미국 종목
# ============================================================
def test_us_simple():
    """미국 종목 — yfinance info만으로."""
    data = {
        "meta": {"country": "US"},
        "info": {
            "trailingPE": 30.0,
            "forwardPE": 22.0,  # forward 낮음 → growth expected
            "priceToBook": 12.0,
            "dividendYield": 0.005,
            "enterpriseToEbitda": 25.0,
        },
    }

    result = calculate_valuation_timeseries(data)
    assert result is not None
    assert result["country"] == "US"

    primary = result["signals"][0]
    print(f"  Primary signal: {primary['label']}")
    print(f"  Narrative: {result['narrative']}")

    # Forward < Trailing → EPS growth expected
    assert primary["label"] == "EPS GROWTH EXPECTED"
    print("✓ 미국 종목 EPS growth expected 시그널")


# ============================================================
# Test 6: 빈 데이터
# ============================================================
def test_empty_data():
    data = {
        "meta": {"country": "KR"},
        "kr_naver_consensus": None,
        "info": {},
    }
    result = calculate_valuation_timeseries(data)
    assert result is None
    print("✓ 빈 한국 데이터 → None")

    data_us = {
        "meta": {"country": "US"},
        "info": {},
    }
    result = calculate_valuation_timeseries(data_us)
    assert result is None
    print("✓ 빈 미국 데이터 → None")


# ============================================================
# Test 7: 임계값 노출 확인 (투명성)
# ============================================================
def test_thresholds_exposed():
    naver_data = _make_naver_data(
        per_series=[15.0, 15.0, 15.0, 15.0, 15.0],
        pbr_series=[1.5] * 5,
        div_yield_series=[2.0] * 5,
    )
    data = {
        "meta": {"country": "KR"},
        "kr_naver_consensus": naver_data,
        "info": {},
        "income_quarterly": pd.DataFrame(),
    }
    result = calculate_valuation_timeseries(data)
    assert result is not None

    # 임계값이 결과에 노출되어야 함 (투명성)
    assert "thresholds" in result
    assert result["thresholds"] == THRESHOLDS
    print(f"✓ 임계값 투명 노출: {list(THRESHOLDS.keys())}")


# ============================================================
# 실행
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Valuation 시계열 검증")
    print("=" * 60)

    print("\n[1] Re-rating opportunity")
    test_rerating_opportunity()

    print("\n[2] Premium territory")
    test_premium_territory()

    print("\n[3] Mean reversion")
    test_mean_reversion()

    print("\n[4] Average metrics")
    test_average_metrics()

    print("\n[5] 미국 종목")
    test_us_simple()

    print("\n[6] 빈 데이터")
    test_empty_data()

    print("\n[7] 임계값 투명 노출")
    test_thresholds_exposed()

    print("\n" + "=" * 60)
    print("✓ 모든 Valuation 시계열 테스트 통과")
    print("=" * 60)
