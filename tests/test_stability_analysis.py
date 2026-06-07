"""
tests/test_stability_analysis.py — Phase 4 검증

4가지 시나리오:
    A. STABLE   — 무차입 IT 기업 (NVDA-like)
    B. ADEQUATE — 정상 제조업 (적정 부채)
    C. STRESSED — 부채 의존 + 유동성 워치 (소매업 일부)
    D. DISTRESS — 영업이익 < 이자 (좀비 기업)

추가:
    E. KR 케이스 — DART에서 합성한 yfinance 영문 라벨 사용 시 정상 동작 확인
    F. 금융 섹터 부채비율 보정
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# 상위 디렉토리 import path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.stability_analysis import analyze  # noqa: E402


# ------------------------------------------------------------
# 헬퍼: 분기 BS DataFrame 만들기
# ------------------------------------------------------------
def make_balance(latest: dict, periods: int = 4) -> pd.DataFrame:
    """
    분기 BS DataFrame. yfinance 컨벤션: index=항목, columns=날짜(최신=좌측).
    latest dict: 항목명 → 최근 분기 값 (이전 분기는 95% 수준으로 잡음)
    """
    # 최신이 좌측 (yfinance 컨벤션) — 단순히 시간 역순으로
    cols = pd.date_range(end="2024-12-31", periods=periods, freq="QE")[::-1]
    data = {}
    for key, val in latest.items():
        # 이전 분기로 갈수록 5%씩 작게
        data[key] = [val * (1 - 0.05 * i) for i in range(periods)]
    return pd.DataFrame(data, index=cols).T


def make_income(quarterly_vals: dict, periods: int = 4) -> pd.DataFrame:
    """
    분기 IS. quarterly_vals dict: 항목명 → 분기당 값 (4분기 동일 가정).
    TTM 합산 → 4 * 분기값.
    """
    cols = pd.date_range(end="2024-12-31", periods=periods, freq="QE")[::-1]
    data = {k: [v] * periods for k, v in quarterly_vals.items()}
    return pd.DataFrame(data, index=cols).T


# ============================================================
# A. STABLE — 무차입 IT
# ============================================================
def test_stable_no_debt_tech():
    """NVDA-like: 부채 거의 없음, 현금 풍부, EBIT 압도적, Altman Z 매우 높음."""
    bs = make_balance({
        "Total Assets":              100_000,
        "Total Liabilities Net Minority Interest": 25_000,
        "Total Debt":                10_000,
        "Current Assets":            50_000,
        "Current Liabilities":       15_000,
        "Inventory":                  5_000,
        "Cash And Cash Equivalents": 30_000,
        "Stockholders Equity":       75_000,
        "Retained Earnings":         40_000,
    })
    is_q = make_income({
        "Total Revenue":      20_000,  # TTM 80,000
        "Operating Income":    8_000,  # TTM 32,000
        "Interest Expense":      100,  # TTM 400 → coverage 80x
        "Normalized EBITDA":   9_500,  # TTM 38,000
    })

    result = analyze(bs, is_q, market_cap=500_000, sector="Technology")

    assert result["overall"] == "STABLE", f"expected STABLE, got {result['overall']}: {result['overall_reason']}"
    m = result["metrics"]
    assert m["debt_ratio"] < 0.15
    assert m["current_ratio"] > 2.0
    assert m["interest_coverage"] > 50
    assert m["altman_z"] > 3.0
    print(f"✓ A. STABLE: overall={result['overall']}, "
          f"debt={m['debt_ratio']:.1%}, CR={m['current_ratio']:.2f}, "
          f"IC={m['interest_coverage']:.0f}x, Z={m['altman_z']:.2f}")


# ============================================================
# B. ADEQUATE — 정상 제조업
# ============================================================
def test_adequate_normal_manufacturer():
    """안정적 제조업: 적정 부채, 유동성 OK, 이자 부담 통제 가능."""
    bs = make_balance({
        "Total Assets":              200_000,
        "Total Liabilities Net Minority Interest": 100_000,
        "Total Debt":                 60_000,    # 부채비율 30%
        "Current Assets":             80_000,
        "Current Liabilities":        50_000,    # 유동 1.6x
        "Inventory":                  20_000,    # 당좌 1.2x
        "Cash And Cash Equivalents":  15_000,
        "Stockholders Equity":       100_000,
        "Retained Earnings":          50_000,
    })
    is_q = make_income({
        "Total Revenue":      40_000,
        "Operating Income":    4_000,  # TTM 16,000
        "Interest Expense":    1_000,  # TTM 4,000 → coverage 4x
        "Normalized EBITDA":   5_500,  # TTM 22,000
    })

    result = analyze(bs, is_q, market_cap=80_000, sector="Industrials")

    assert result["overall"] in {"STABLE", "ADEQUATE"}, f"got {result['overall']}"
    m = result["metrics"]
    assert 0.25 < m["debt_ratio"] < 0.40
    assert 1.5 <= m["current_ratio"] < 2.0
    assert 3.0 <= m["interest_coverage"] < 8.0
    print(f"✓ B. ADEQUATE: overall={result['overall']}, "
          f"debt={m['debt_ratio']:.1%}, CR={m['current_ratio']:.2f}, "
          f"IC={m['interest_coverage']:.1f}x, Z={m['altman_z']:.2f}")


# ============================================================
# C. STRESSED — 부채 의존 + 유동성 워치
# ============================================================
def test_stressed_leveraged_retail():
    """부채 65%, 유동성 약함, 이자 보상 1.5~3x."""
    bs = make_balance({
        "Total Assets":              100_000,
        "Total Liabilities Net Minority Interest":  68_000,
        "Total Debt":                 50_000,   # 부채비율 50% (Total Debt 기준)
        "Current Assets":             30_000,
        "Current Liabilities":        25_000,   # CR 1.2x (watch)
        "Inventory":                  15_000,   # QR 0.6x (watch)
        "Cash And Cash Equivalents":   3_000,
        "Stockholders Equity":        32_000,
        "Retained Earnings":           8_000,
    })
    is_q = make_income({
        "Total Revenue":      25_000,
        "Operating Income":    1_000,   # TTM 4,000
        "Interest Expense":      600,   # TTM 2,400 → coverage 1.67x (watch)
        "Normalized EBITDA":   1_500,
    })

    result = analyze(bs, is_q, market_cap=20_000, sector="Consumer Cyclical")

    assert result["overall"] in {"STRESSED", "DISTRESS"}, f"got {result['overall']}"
    m = result["metrics"]
    assert m["current_ratio"] < 1.5
    assert m["quick_ratio"] < 0.7
    assert m["interest_coverage"] < 3.0
    print(f"✓ C. STRESSED: overall={result['overall']}, "
          f"debt={m['debt_ratio']:.1%}, CR={m['current_ratio']:.2f}, "
          f"QR={m['quick_ratio']:.2f}, IC={m['interest_coverage']:.2f}x, Z={m['altman_z']:.2f}")


# ============================================================
# D. DISTRESS — 영업이익 < 이자 (좀비)
# ============================================================
def test_distress_zombie():
    """영업이익으로 이자 못 갚음 → 즉시 DISTRESS."""
    bs = make_balance({
        "Total Assets":              100_000,
        "Total Liabilities Net Minority Interest":  85_000,
        "Total Debt":                 70_000,   # 부채비율 70% (warning)
        "Current Assets":             20_000,
        "Current Liabilities":        25_000,   # CR 0.8x (warning)
        "Inventory":                  10_000,
        "Cash And Cash Equivalents":   1_500,
        "Stockholders Equity":        15_000,
        "Retained Earnings":          -5_000,   # 결손
    })
    is_q = make_income({
        "Total Revenue":      15_000,
        "Operating Income":      500,   # TTM 2,000
        "Interest Expense":    1_000,   # TTM 4,000 → coverage 0.5x (distress)
        "Normalized EBITDA":     800,
    })

    result = analyze(bs, is_q, market_cap=5_000, sector="Consumer Cyclical")

    assert result["overall"] == "DISTRESS", f"expected DISTRESS, got {result['overall']}"
    m = result["metrics"]
    assert m["interest_coverage"] < 1.0
    # 알람 flag 있어야 함
    assert any(f["severity"] == "alert" for f in result["flags"])
    print(f"✓ D. DISTRESS: overall={result['overall']}, "
          f"IC={m['interest_coverage']:.2f}x, Z={m['altman_z']:.2f}, "
          f"flags={len(result['flags'])}개")


# ============================================================
# E. KR 케이스 — DART 정규화 라벨로 동일하게 동작
# ============================================================
def test_korea_dart_labels():
    """DART → yfinance 영문 라벨 정규화된 데이터로 동일하게 분석."""
    # 삼성전자 가상 (KRW 백만)
    bs = make_balance({
        "Total Assets":             450_000_000,
        "Total Liabilities Net Minority Interest": 90_000_000,
        "Current Debt":               5_000_000,
        "Long Term Debt":             3_000_000,  # Total Debt 합성 테스트
        "Current Assets":           200_000_000,
        "Current Liabilities":       60_000_000,
        "Inventory":                 50_000_000,
        "Cash And Cash Equivalents": 80_000_000,
        "Stockholders Equity":      360_000_000,
        "Retained Earnings":        300_000_000,
    })
    is_q = make_income({
        "Total Revenue":      75_000_000,
        "Operating Income":   15_000_000,
        "Interest Expense":      150_000,
    })

    result = analyze(bs, is_q, market_cap=400_000_000, sector="Technology")

    m = result["metrics"]
    # Total Debt 합성 확인 (5M + 3M = 8M)
    assert m["raw"]["total_debt"] == 8_000_000
    assert m["debt_ratio"] is not None
    assert m["interest_coverage"] > 50
    assert result["overall"] == "STABLE"
    print(f"✓ E. KR (DART labels): Total Debt 합성={m['raw']['total_debt']:,}, "
          f"overall={result['overall']}, Z={m['altman_z']:.2f}")


# ============================================================
# F. 금융 섹터 — 부채비율 70%여도 warning 안 잡아야 함
# ============================================================
def test_financials_high_debt_ok():
    """은행: 부채비율 90%는 정상 — sector_normal로 처리되어야."""
    bs = make_balance({
        "Total Assets":              1_000_000,
        "Total Liabilities Net Minority Interest": 900_000,
        "Total Debt":                  800_000,   # 부채비율 80%
        "Current Assets":              400_000,
        "Current Liabilities":         300_000,
        "Inventory":                         0,
        "Cash And Cash Equivalents":   200_000,
        "Stockholders Equity":         100_000,
        "Retained Earnings":            50_000,
    })
    is_q = make_income({
        "Total Revenue":      50_000,
        "Operating Income":   15_000,
        "Interest Expense":    5_000,
    })

    result = analyze(bs, is_q, market_cap=150_000, sector="Financial Services")

    # 금융업 부채비율은 warning이 아니라 sector_normal
    assert result["ratings"]["debt_ratio"] == "sector_normal"
    # 부채비율 flag 없어야 함
    debt_flags = [f for f in result["flags"] if "Debt ratio" in f.get("msg", "")]
    assert len(debt_flags) == 0
    print(f"✓ F. Financials: debt={result['metrics']['debt_ratio']:.1%}, "
          f"rating={result['ratings']['debt_ratio']}, overall={result['overall']}")


# ============================================================
# G. 결측 강건성 — 일부 필드 None이어도 죽지 않음
# ============================================================
def test_resilience_missing_fields():
    """일부 필드 결측 시 None 반환 + crash 없이 분석 완료."""
    bs = make_balance({
        "Total Assets":              100_000,
        # Total Liabilities 결측
        "Current Assets":             40_000,
        "Current Liabilities":        20_000,
        # Inventory 결측 → 0 처리
        "Stockholders Equity":        60_000,
    })
    is_q = make_income({
        "Total Revenue":     20_000,
        "Operating Income":   3_000,
        # Interest Expense 결측 → coverage None
    })

    result = analyze(bs, is_q, market_cap=None, sector="Technology")

    # crash 없이 반환, 일부 None
    assert result["metrics"]["current_ratio"] == 2.0
    assert result["metrics"]["interest_coverage"] is None
    assert result["overall"] in {"STABLE", "ADEQUATE", "STRESSED", "DISTRESS"}
    print(f"✓ G. Resilience: missing fields OK, overall={result['overall']}, "
          f"interest_cov={result['metrics']['interest_coverage']}")


# ============================================================
# 실행
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Phase 4: Stability Analysis — Test Suite")
    print("=" * 60)
    test_stable_no_debt_tech()
    test_adequate_normal_manufacturer()
    test_stressed_leveraged_retail()
    test_distress_zombie()
    test_korea_dart_labels()
    test_financials_high_debt_ok()
    test_resilience_missing_fields()
    print("=" * 60)
    print("✓ 7 시나리오 모두 통과")
    print("=" * 60)
