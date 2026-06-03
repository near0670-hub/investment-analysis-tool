"""
tests/test_dupont.py — 듀퐁 분해 검증

핵심 시나리오:
1. 한국 종목 (네이버 데이터 + DART balance) - 본인 책 이미지의 삼성전자 수치 재현
2. 미국 종목 (yfinance only)
3. 빈 데이터 처리
4. 한 줄 해설 자동 생성
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.dupont_decomposition import calculate_dupont


# ============================================================
# 한국 종목: 삼성전자 시나리오 (본인 책 이미지 재현)
# ============================================================
def test_korean_samsung_scenario():
    """
    본인 책 이미지 데이터:
    - 2024년: 매출 300.9조, 순이익 33.6조, 자산 514.5조, 자본(지배) 391.7조 → ROE 9.0%
    - 2025년: 매출 333.6조, 순이익 44.3조, 자산 567.0조, 자본 424.3조 → ROE 10.8%
    - 2026E: 매출 684.7조, 순이익 287.5조, 자산 895.4조, 자본 692.9조 → ROE 51.5%
    """
    # 네이버 annual DataFrame 모킹
    naver_annual_cols = [
        pd.Timestamp("2023-12-31"),
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2025-12-31"),
        pd.Timestamp("2026-12-31"),
    ]
    naver_annual = pd.DataFrame(
        index=["Total Revenue", "Net Income", "Net Margin", "ROE"],
        columns=naver_annual_cols,
        data=[
            # 2023, 2024, 2025, 2026E (단위 = 원)
            [258.9e12, 300.9e12, 333.6e12, 684.7e12],  # 매출
            [15.5e12, 33.6e12, 44.3e12, 287.5e12],     # 순이익
            [6.0, 11.17, 13.27, 41.99],                # 순이익률(%)
            [4.5, 9.03, 10.85, 51.46],                  # ROE(%)
        ],
    )

    naver_data = {
        "annual": naver_annual,
        "quarterly": pd.DataFrame(),
        "future_periods": ["2026.12(E)"],
        "source": "naver",
    }

    # DART balance_annual 모킹
    balance_cols = [
        pd.Timestamp("2022-12-31"),
        pd.Timestamp("2023-12-31"),
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2025-12-31"),
    ]
    balance_annual = pd.DataFrame(
        index=["Total Assets", "Stockholders Equity"],
        columns=balance_cols,
        data=[
            [448e12, 480e12, 514.5e12, 567.0e12],   # 자산 (2022 기말 = 2023 기초)
            [354e12, 376e12, 391.7e12, 424.3e12],   # 자본
        ],
    )

    data = {
        "meta": {"country": "KR"},
        "kr_naver_consensus": naver_data,
        "balance_annual": balance_annual,
        "income_annual": pd.DataFrame(),  # 안 씀
        "info": {},
    }

    result = calculate_dupont(data, n_history=2)
    assert result is not None, "duPont 결과가 None"
    assert result["country"] == "KR"

    df = result["components"]
    assert len(df) == 3, f"Expected 3 rows (FY24, FY25, FY26E), got {len(df)}"

    # FY25 검증
    fy25 = df[df["period"] == "FY25"].iloc[0]

    # 순이익률: 13.27% (네이버 직접)
    assert abs(fy25["net_margin"] - 0.1327) < 0.001, \
        f"Margin: expected 13.27%, got {fy25['net_margin']*100:.2f}%"

    # 자산회전율: 매출 333.6조 / 평균자산 540.75조 = 0.617
    # (514.5 + 567.0)/2 = 540.75
    expected_turnover = 333.6 / ((514.5 + 567.0) / 2)
    assert abs(fy25["asset_turnover"] - expected_turnover) < 0.01, \
        f"Asset turnover: expected {expected_turnover:.2f}, got {fy25['asset_turnover']:.2f}"

    # 레버리지: 평균자산 540.75 / 평균자본 408.0 = 1.326
    # 평균자본 = (391.7 + 424.3)/2 = 408.0
    expected_leverage = ((514.5 + 567.0) / 2) / ((391.7 + 424.3) / 2)
    assert abs(fy25["leverage"] - expected_leverage) < 0.01, \
        f"Leverage: expected {expected_leverage:.2f}, got {fy25['leverage']:.2f}"

    # ROE: 네이버 표시값 10.85%
    assert abs(fy25["roe_display"] - 0.1085) < 0.001, \
        f"ROE: expected 10.85%, got {fy25['roe_display']*100:.2f}%"

    print(f"✓ 삼성전자 FY25: 순이익률 {fy25['net_margin']*100:.2f}%, "
          f"자산회전율 {fy25['asset_turnover']:.2f}배, "
          f"레버리지 {fy25['leverage']:.2f}배, "
          f"ROE {fy25['roe_display']*100:.2f}%")

    # 컨센서스 행 확인
    fy26 = df[df["period"] == "FY26"].iloc[0]
    assert fy26["is_consensus"] == True
    assert abs(fy26["roe_display"] - 0.5146) < 0.01

    print(f"✓ 삼성전자 FY26E: ROE {fy26['roe_display']*100:.2f}% (consensus)")

    # 동인 분해 확인
    roe_change = result["roe_change_components"]
    assert len(roe_change["periods"]) == 2  # FY24→FY25, FY25→FY26E

    last_change = roe_change["periods"][-1]  # FY25→FY26E
    assert last_change["d_roe"] > 0  # ROE 상승
    assert last_change["margin_effect"] is not None
    print(f"✓ 동인 분해: FY25→FY26E ROE +{last_change['d_roe']*100:.1f}p.p., "
          f"margin effect {last_change['margin_effect']*100:.1f}p.p.")

    # 해설 자동 생성
    narrative = result["narrative"]
    assert narrative
    assert "FY25" in narrative or "FY26" in narrative
    print(f"✓ Narrative: {narrative}")


# ============================================================
# 미국 종목: yfinance only
# ============================================================
def test_us_simple_scenario():
    """미국 종목 간단 시나리오 (가상 데이터)."""
    income_annual = pd.DataFrame(
        index=["Total Revenue", "Net Income"],
        columns=[pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31"),
                 pd.Timestamp("2025-12-31")],
        data=[
            [100e9, 120e9, 150e9],
            [20e9, 28e9, 40e9],
        ],
    )
    balance_annual = pd.DataFrame(
        index=["Total Assets", "Stockholders Equity"],
        columns=[pd.Timestamp("2022-12-31"), pd.Timestamp("2023-12-31"),
                 pd.Timestamp("2024-12-31"), pd.Timestamp("2025-12-31")],
        data=[
            [180e9, 200e9, 230e9, 260e9],
            [80e9, 90e9, 105e9, 125e9],
        ],
    )

    data = {
        "meta": {"country": "US"},
        "income_annual": income_annual,
        "balance_annual": balance_annual,
        "info": {"forwardEps": 15.0, "sharesOutstanding": 1e9},
    }

    result = calculate_dupont(data, n_history=2)
    assert result is not None
    assert result["country"] == "US"

    df = result["components"]
    assert len(df) >= 2  # FY24, FY25 (+ optional FY26E)

    # FY25 (가장 최근 actual) 검증
    fy25 = df[df["period"] == "FY25"].iloc[0]
    # 순이익률 = 40/150 = 26.67%
    assert abs(fy25["net_margin"] - 40 / 150) < 0.001
    # 자산회전율 = 150 / (230+260)/2 = 150/245 = 0.612
    expected_turnover = 150e9 / ((230e9 + 260e9) / 2)
    assert abs(fy25["asset_turnover"] - expected_turnover) < 0.01
    # 레버리지 = 245/115 = 2.13
    expected_leverage = ((230e9 + 260e9) / 2) / ((105e9 + 125e9) / 2)
    assert abs(fy25["leverage"] - expected_leverage) < 0.01

    print(f"✓ US 시나리오 FY25: margin {fy25['net_margin']*100:.1f}%, "
          f"turnover {fy25['asset_turnover']:.2f}x, "
          f"leverage {fy25['leverage']:.2f}x, "
          f"ROE {fy25['roe_display']*100:.1f}%")

    # 컨센서스 행 (forwardEps 활용)
    consensus_rows = df[df["is_consensus"] == True]
    if len(consensus_rows) > 0:
        fc = consensus_rows.iloc[0]
        print(f"✓ US 컨센서스 ({fc['period']}): ROE {fc['roe_display']*100:.1f}% (extrapolated)")

    assert "US-GAAP" in result["source_note"]
    print(f"✓ Source note: {result['source_note']}")


# ============================================================
# 빈 데이터 처리
# ============================================================
def test_empty_data():
    data = {
        "meta": {"country": "KR"},
        "kr_naver_consensus": None,
        "balance_annual": pd.DataFrame(),
        "income_annual": pd.DataFrame(),
        "info": {},
    }
    result = calculate_dupont(data)
    assert result is None
    print("✓ 빈 데이터: None 반환")

    # 미국 빈 데이터
    data_us = {
        "meta": {"country": "US"},
        "income_annual": pd.DataFrame(),
        "balance_annual": pd.DataFrame(),
        "info": {},
    }
    result = calculate_dupont(data_us)
    assert result is None
    print("✓ 미국 빈 데이터: None 반환")


# ============================================================
# 해설 시그널 분류 테스트
# ============================================================
def test_signal_classification():
    """3가지 변화 패턴이 정확한 시그널을 만드는지."""
    from modules.dupont_decomposition import _classify_signal

    # 마진 + 자산회전율 둘 다 개선
    s = _classify_signal(0.02, 0.05, 0.0)
    assert s is not None
    assert "Operating leverage" in s
    print(f"✓ Margin+Turnover 개선 → '{s}'")

    # 마진만 개선
    s = _classify_signal(0.02, 0.0, 0.0)
    assert s is not None
    assert "margin-driven" in s.lower() or "healthy" in s.lower()
    print(f"✓ Margin only → '{s}'")

    # 레버리지만 증가
    s = _classify_signal(0.0, 0.0, 0.05)
    assert s is not None
    assert "leverage" in s.lower()
    print(f"✓ Leverage only → '{s}'")

    # 둘 다 악화
    s = _classify_signal(-0.02, -0.05, 0.0)
    assert s is not None
    assert "Deteriorating" in s
    print(f"✓ Margin+Turnover 악화 → '{s}'")


# ============================================================
# 실행
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("DuPont 듀퐁 분해 검증")
    print("=" * 60)

    test_korean_samsung_scenario()
    print()
    test_us_simple_scenario()
    print()
    test_empty_data()
    print()
    test_signal_classification()

    print()
    print("=" * 60)
    print("✓ 모든 듀퐁 테스트 통과")
    print("=" * 60)
