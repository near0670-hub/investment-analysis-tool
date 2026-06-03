"""
tests/test_valuation.py — PEG 3변형 + Trap Detection 검증

핵심 시나리오:
1. PEG 판정 (✓✓ / ✓ / △ / ⚠ / ✗)
2. PEG 계산 불가 케이스 (적자, 역성장, 데이터 부족)
3. Trap Detection (성장률 과도, 매출-EPS 갭, 사이클 정점)
4. NVDA 유사 가상 데이터로 통합 테스트
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.valuation_analysis import (
    analyze_valuation, _calculate_peg, _peg_verdict,
)


def _build_df(rows: dict, n: int) -> pd.DataFrame:
    """행=항목, 열=분기말 일자 형식의 DataFrame."""
    end = pd.Timestamp("2025-12-31")
    cols = [end - pd.DateOffset(months=3 * i) for i in range(n)]
    df = pd.DataFrame(index=list(rows.keys()), columns=cols, dtype=float)
    for row_name, values in rows.items():
        for i, col in enumerate(cols):
            if i < len(values):
                df.at[row_name, col] = values[i]
    return df


def _build_annual_df(rows: dict, n: int) -> pd.DataFrame:
    end = pd.Timestamp("2025-12-31")
    cols = [end - pd.DateOffset(years=i) for i in range(n)]
    df = pd.DataFrame(index=list(rows.keys()), columns=cols, dtype=float)
    for row_name, values in rows.items():
        for i, col in enumerate(cols):
            if i < len(values):
                df.at[row_name, col] = values[i]
    return df


# ============================================================
# 1. PEG 판정 룰
# ============================================================
def test_peg_verdict_rules():
    assert _peg_verdict(0.3) == "✓✓"
    assert _peg_verdict(0.8) == "✓"
    assert _peg_verdict(1.2) == "△"
    assert _peg_verdict(1.7) == "⚠"
    assert _peg_verdict(2.5) == "✗"
    print("✓ PEG 판정 룰 (5단계) OK")


# ============================================================
# 2. PEG 계산 — 정상 케이스
# ============================================================
def test_peg_normal_case():
    # NVDA 유사: Forward PER 38, 향후 2년 EPS CAGR 45%
    result = _calculate_peg(per=38.0, growth_rate=0.45, label="Forward 2Y")
    assert result["value"] is not None
    assert abs(result["value"] - 0.844) < 0.01, f"Expected ~0.844, got {result['value']}"
    assert result["verdict"] == "✓"
    print(f"✓ PEG 정상: PER 38 / 45% = {result['value']:.3f} → {result['verdict']}")


def test_peg_very_attractive():
    """피터 린치 기준 매우 매력적 (PEG < 0.5)"""
    result = _calculate_peg(per=15.0, growth_rate=0.35)
    assert result["verdict"] == "✓✓"
    print(f"✓ PEG ✓✓: {result['value']:.3f}")


# ============================================================
# 3. PEG 계산 불가 케이스
# ============================================================
def test_peg_negative_per():
    """적자 기업"""
    result = _calculate_peg(per=-20.0, growth_rate=0.30)
    assert result["value"] is None
    assert result["verdict"] == "N/A"
    assert "적자" in result["note"]
    print(f"✓ PEG 적자: N/A — {result['note']}")


def test_peg_negative_growth():
    """역성장"""
    result = _calculate_peg(per=15.0, growth_rate=-0.10)
    assert result["value"] is None
    assert result["verdict"] == "N/A"
    assert "역성장" in result["note"]
    print(f"✓ PEG 역성장: N/A — {result['note']}")


def test_peg_missing_growth():
    """성장률 데이터 없음"""
    result = _calculate_peg(per=20.0, growth_rate=None)
    assert result["value"] is None
    assert result["verdict"] == "N/A"
    print(f"✓ PEG 성장률 누락: N/A")


def test_peg_low_growth_warning():
    """5% 미만 성장률 — 계산은 하지만 의미 약함"""
    result = _calculate_peg(per=10.0, growth_rate=0.03)
    assert result["value"] is not None
    assert result["verdict"] == "⚠"
    print(f"✓ PEG 저성장 경고: {result['value']:.2f} {result['verdict']}")


# ============================================================
# 4. 통합 테스트 — 가상 NVDA
# ============================================================
def test_analyze_valuation_full_nvda_like():
    """NVDA 유사: 고PER + 고성장 → PEG로 보면 매력적 + 사이클 정점 경고"""
    income_q = _build_df({
        "Total Revenue":    [35000, 30000, 26000, 18000, 13500, 7200, 6700, 6050],
        "Operating Income": [21000, 17000, 14000, 8500, 5500, 1500, 1300, 1100],
        "Net Income":       [18000, 14800, 12000, 7100, 4400, 1300, 1100, 950],
        "Diluted EPS":      [7.20, 5.92, 4.80, 2.84, 1.76, 0.52, 0.44, 0.38],
        "Gross Profit":     [26000, 22000, 18000, 12000, 8400, 4000, 3700, 3340],
        "EBITDA":           [22000, 18000, 14500, 9000, 6000, 1700, 1500, 1300],
        "Reconciled Depreciation": [1000, 1000, 1000, 500, 500, 200, 200, 200],
    }, n=8)

    income_a = _build_annual_df({
        "Total Revenue":    [120000, 60000, 26900, 16700],
        "Net Income":       [56000, 30000, 4400, 9700],
        "Diluted EPS":      [22.4, 12.0, 1.76, 3.88],
        "Operating Income": [70000, 35000, 5500, 10500],
    }, n=4)

    balance_q = _build_df({
        "Total Assets":        [70000, 65000, 60000, 55000],
        "Stockholders Equity": [50000, 45000, 40000, 36000],
        "Cash And Cash Equivalents": [25000, 22000, 20000, 18000],
        "Total Debt":          [10000, 10000, 10000, 10000],
    }, n=4)

    data = {
        "meta": {
            "market_cap": 3_000_000_000_000,  # $3T
            "sector_internal": "TECH_AI_INFRA",
            "currency": "USD",
        },
        "info": {
            "currentPrice": 1200.0,
            "forwardEps": 30.0,  # 1년 뒤 EPS 컨센서스
            "trailingEps": 22.4,
        },
        "income_quarterly":  income_q,
        "income_annual":     income_a,
        "balance_quarterly": balance_q,
        "balance_annual":    pd.DataFrame(),
        "cashflow_quarterly": pd.DataFrame(),
    }

    # 사용자가 2년 뒤 EPS 추정치 입력 (예: 40달러)
    result = analyze_valuation(
        data,
        user_forward_eps_2y=40.0,
    )

    m = result["metrics"]
    print(f"\n[NVDA 유사 가상 분석]")
    print(f"  PER(TTM):        {m['per_ttm']:.1f}배" if m['per_ttm'] else "  PER(TTM): N/A")
    print(f"  Forward PER 1Y:  {m['forward_per_1y']:.1f}배" if m['forward_per_1y'] else "  Forward PER 1Y: N/A")
    print(f"  Forward PER 2Y:  {m['forward_per_2y']:.1f}배" if m['forward_per_2y'] else "  Forward PER 2Y: N/A")
    print(f"  PBR:             {m['pbr']:.2f}배" if m['pbr'] else "  PBR: N/A")
    print()
    print(f"  PEG (TTM):       {m['peg_ttm']['value']:.2f} {m['peg_ttm']['verdict']}" if m['peg_ttm']['value'] else f"  PEG (TTM):     {m['peg_ttm']['verdict']} ({m['peg_ttm']['note']})")
    print(f"  PEG (Fwd 1Y):    {m['peg_forward_1y']['value']:.2f} {m['peg_forward_1y']['verdict']}" if m['peg_forward_1y']['value'] else "  PEG (Fwd 1Y): N/A")
    print(f"  PEG (Fwd 2Y) ★:  {m['peg_forward_2y']['value']:.2f} {m['peg_forward_2y']['verdict']}" if m['peg_forward_2y']['value'] else "  PEG (Fwd 2Y): N/A")
    print()
    print(f"  Flag 개수: {len(result['flags'])}")
    for f in result['flags']:
        print(f"    [{f['severity']}] {f['msg']}")
    print()
    print(f"  해석: {result['interpretation']}")

    # 검증
    assert m['per_ttm'] is not None, "TTM PER 계산 가능해야 함"
    assert m['peg_forward_2y']['value'] is not None, "메인 PEG 계산 가능해야 함"


# ============================================================
# 5. Trap Detection — 사이클 정점
# ============================================================
def test_trap_cycle_peak():
    """반도체 + 마진 사상 최고 → cycle_peak 플래그"""
    income_q = _build_df({
        "Total Revenue":    [100, 95, 90, 85],
        "Operating Income": [55, 50, 45, 40],   # OPM 55%, 사상 최고
        "Net Income":       [40, 38, 35, 30],
        "Diluted EPS":      [4.0, 3.8, 3.5, 3.0],
    }, n=4)

    income_a = _build_annual_df({
        "Total Revenue":    [400, 300, 200, 150],
        "Operating Income": [200, 100, 50, 30],   # 과거 OPM: 50%, 33%, 25%, 20%
        "Net Income":       [150, 80, 40, 25],
        "Diluted EPS":      [15, 8, 4, 2.5],
    }, n=4)

    data = {
        "meta": {
            "market_cap": 1_000_000_000_000,
            "sector_internal": "SEMICONDUCTOR_MEM",  # 사이클 산업
            "currency": "USD",
        },
        "info": {"currentPrice": 100.0, "trailingEps": 15.0, "forwardEps": 18.0},
        "income_quarterly":  income_q,
        "income_annual":     income_a,
        "balance_quarterly": pd.DataFrame(),
        "balance_annual":    pd.DataFrame(),
        "cashflow_quarterly": pd.DataFrame(),
    }

    result = analyze_valuation(data, user_forward_eps_2y=22.0)
    trap_types = {f["type"] for f in result["flags"]}
    assert "cycle_peak" in trap_types, f"cycle_peak 플래그 있어야 함. Got: {trap_types}"
    print(f"✓ Trap cycle_peak 감지: 반도체 + 마진 55% (역사 최고)")


# ============================================================
# 6. Trap Detection — 성장률 과도
# ============================================================
def test_trap_growth_too_high():
    """100% 성장 컨센서스 → 비현실적 경고"""
    income_q = _build_df({
        "Total Revenue":    [100],
        "Operating Income": [20],
        "Net Income":       [10],
        "Diluted EPS":      [1.0],
    }, n=1)

    data = {
        "meta": {"market_cap": 100, "sector_internal": "SOFTWARE_SAAS"},
        "info": {"currentPrice": 50.0, "trailingEps": 1.0},
        "income_quarterly":  income_q,
        "income_annual":     pd.DataFrame(),
        "balance_quarterly": pd.DataFrame(),
        "balance_annual":    pd.DataFrame(),
        "cashflow_quarterly": pd.DataFrame(),
    }

    # 2년 후 EPS가 현재의 5배 → CAGR 약 124%
    result = analyze_valuation(data, user_forward_eps_2y=5.0)
    trap_types = {f["type"] for f in result["flags"]}
    assert "growth_too_high" in trap_types, f"growth_too_high 있어야 함. Got: {trap_types}"
    print(f"✓ Trap growth_too_high 감지: 향후 2년 EPS CAGR > 50%")


# ============================================================
# 실행
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("PEG 3변형 + Trap Detection 검증")
    print("=" * 60)

    print("\n--- 1. PEG 판정 룰 ---")
    test_peg_verdict_rules()

    print("\n--- 2. PEG 정상 케이스 ---")
    test_peg_normal_case()
    test_peg_very_attractive()

    print("\n--- 3. PEG 계산 불가 케이스 ---")
    test_peg_negative_per()
    test_peg_negative_growth()
    test_peg_missing_growth()
    test_peg_low_growth_warning()

    print("\n--- 4. 통합 (NVDA 유사) ---")
    test_analyze_valuation_full_nvda_like()

    print("\n--- 5. Trap: 사이클 정점 ---")
    test_trap_cycle_peak()

    print("\n--- 6. Trap: 성장률 과도 ---")
    test_trap_growth_too_high()

    print("\n" + "=" * 60)
    print("✓ 모든 밸류에이션 테스트 통과")
    print("=" * 60)
