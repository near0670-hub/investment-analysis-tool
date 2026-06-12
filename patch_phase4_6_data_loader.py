"""
patch_phase4_6_data_loader.py — Phase 4.6.3 + 4.6.5

SEC EDGAR 분기 데이터 보강 + 부제 문구 country별 수정.

변경 사항:
    1. data_loader.py:
       - sec_data 변수 초기화 (한국/미국 분기 위쪽)
       - 미국 else 블록 안에 fetch_sec_edgar_quarterly 호출
       - 재무제표 병합 끝에 미국 income_quarterly에 SEC EDGAR 병합

전제:
    - Phase 4.5 패치 (patch_step2) 이미 적용된 상태
    - Phase 4.6.1 (sec_edgar_source.py) 이미 modules/data_sources/에 복사된 상태

실행:
    python patch_phase4_6_data_loader.py

안전장치:
    - 백업 자동 생성
    - 멱등성 (재실행 안전)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


DL = Path("modules/data_loader.py")
DL_BAK = Path("modules/data_loader.py.bak.phase4_6")
SEC_SRC = Path("modules/data_sources/sec_edgar_source.py")


# ============================================================
# 패치 1: sec_data = {} 초기화 (한국/미국 분기 위쪽)
# ============================================================
OLD_INIT = '''    dart_data = {}
    pykrx_data = {}
    naver_data = None

    if country == "KR":'''

NEW_INIT = '''    dart_data = {}
    pykrx_data = {}
    naver_data = None
    sec_data = {}

    if country == "KR":'''


# ============================================================
# 패치 2: 미국 else 블록 안에 SEC EDGAR 호출 추가
#         (Phase 4.5에서 추가한 yf_consensus 블록 끝 다음)
# ============================================================
OLD_US_BLOCK_END = '''        except Exception as e:
            naver_data = None
            if verbose:
                print(f"  [yf_consensus error, gracefully skipped] {e}")

    # ============================================================
    # 5. 재무제표 병합 (한국 종목은 DART 우선)
    # ============================================================'''

NEW_US_BLOCK_END = '''        except Exception as e:
            naver_data = None
            if verbose:
                print(f"  [yf_consensus error, gracefully skipped] {e}")

        # ============================================================
        # Phase 4.6: SEC EDGAR 분기 데이터 보강
        # yfinance 5분기 한계 해결 → 8~12분기로 확장하여 YoY 매칭 가능
        # ⚠️ 실패해도 앱 안 죽음 (graceful degradation)
        # ============================================================
        try:
            from modules.data_sources.sec_edgar_source import fetch_sec_edgar_quarterly
            sec_result = fetch_sec_edgar_quarterly(ticker, n_quarters=12, verbose=verbose)
            if sec_result["n_quarters"] > 0:
                sec_data["income_quarterly"] = sec_result["income_quarterly"]
                sources_used.append("sec_edgar")
                if verbose:
                    print(f"  [sec_edgar] {sec_result['n_quarters']} quarters loaded "
                          f"(concepts: {sec_result['concepts_used']})")
        except Exception as e:
            if verbose:
                print(f"  [sec_edgar error, gracefully skipped] {e}")

    # ============================================================
    # 5. 재무제표 병합 (한국 종목은 DART 우선)
    # ============================================================'''


# ============================================================
# 패치 3: 재무제표 병합 끝에 미국 SEC EDGAR 병합 추가
# ============================================================
OLD_MERGE_END = '''    cashflow_annual = _merge_financial_statements(
        yf_data.get("cashflow_annual", pd.DataFrame()),
        dart_data.get("cashflow_annual", pd.DataFrame()),
        prefer=prefer_source,
    )

    # ============================================================
    # 5-B. 한국 종목: Q4 누적값 보정 (DART 사업보고서 이슈)'''

NEW_MERGE_END = '''    cashflow_annual = _merge_financial_statements(
        yf_data.get("cashflow_annual", pd.DataFrame()),
        dart_data.get("cashflow_annual", pd.DataFrame()),
        prefer=prefer_source,
    )

    # ============================================================
    # Phase 4.6: 미국 종목 income_quarterly에 SEC EDGAR 병합
    # yfinance 5분기 + SEC EDGAR 12분기 → 합치면 ~15분기 시계열
    # 모든 actual 분기 YoY 계산 가능
    # ============================================================
    if (country == "US"
            and sec_data.get("income_quarterly") is not None
            and not sec_data["income_quarterly"].empty):
        income_quarterly = _merge_financial_statements(
            income_quarterly,                # 기존 (yfinance) 결과
            sec_data["income_quarterly"],    # SEC EDGAR (12 quarters)
            prefer="dart",  # 두 번째 인자 (SEC) 우선
        )

    # ============================================================
    # 5-B. 한국 종목: Q4 누적값 보정 (DART 사업보고서 이슈)'''


def main() -> int:
    if not DL.exists():
        print(f"✗ {DL} 없음.")
        return 1
    if not SEC_SRC.exists():
        print(f"✗ {SEC_SRC} 없음.")
        print("  먼저 Phase 4.6.1 (sec_edgar_source.py)을 modules/data_sources/에 복사하세요.")
        return 1

    text = DL.read_text()

    # 사전 점검 — Phase 4.5 적용된 상태여야 함
    if "yf_consensus" not in text:
        print("✗ Phase 4.5 미적용 (yf_consensus 흔적 없음).")
        print("  먼저 patch_step2_us_forward_integration.py 실행하세요.")
        return 1

    # 백업
    if not DL_BAK.exists():
        shutil.copy(DL, DL_BAK)
        print(f"✓ 백업: {DL_BAK}")
    else:
        print(f"⚠ {DL_BAK} 이미 존재 — 덮어쓰지 않음")

    # ============================================================
    # 패치 1: sec_data 초기화
    # ============================================================
    if "sec_data = {}" in text:
        print("✓ [1/3] sec_data 초기화 — 이미 적용됨")
    elif OLD_INIT in text:
        text = text.replace(OLD_INIT, NEW_INIT, 1)
        print("✓ [1/3] sec_data 초기화 추가")
    else:
        print("✗ [1/3] 초기화 위치 패턴 못 찾음")
        return 1

    # ============================================================
    # 패치 2: 미국 SEC EDGAR 호출
    # ============================================================
    if "[sec_edgar]" in text:
        print("✓ [2/3] SEC EDGAR 호출 블록 — 이미 적용됨")
    elif OLD_US_BLOCK_END in text:
        text = text.replace(OLD_US_BLOCK_END, NEW_US_BLOCK_END, 1)
        print("✓ [2/3] SEC EDGAR 호출 블록 추가")
    else:
        print("✗ [2/3] 미국 else 블록 끝 패턴 못 찾음 (Phase 4.5 적용 확인하세요)")
        return 1

    # ============================================================
    # 패치 3: 재무제표 병합 끝에 SEC EDGAR 병합
    # ============================================================
    if "SEC EDGAR (12 quarters)" in text:
        print("✓ [3/3] income_quarterly SEC 병합 — 이미 적용됨")
    elif OLD_MERGE_END in text:
        text = text.replace(OLD_MERGE_END, NEW_MERGE_END, 1)
        print("✓ [3/3] income_quarterly SEC 병합 추가")
    else:
        print("✗ [3/3] 재무제표 병합 끝 패턴 못 찾음")
        return 1

    DL.write_text(text)
    print()
    print("=" * 60)
    print("✓ Phase 4.6.3 통합 완료")
    print("=" * 60)
    print()
    print("다음 단계:")
    print("  1) 캐시 청소 + Streamlit 재시작:")
    print("     find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null")
    print("     pkill -f streamlit ; sleep 2 ; streamlit run app.py")
    print()
    print("  2) AAPL 또는 NVDA 조회 → GROWTH 탭")
    print("     기대 결과:")
    print("       - QUARTERLY 표: 4 actual + 2 forward 행 (Phase 4.5와 동일)")
    print("       - 모든 actual 행에 Revenue YoY + EPS YoY 계산됨 (3Q25, 4Q25, 1Q26)")
    print("       - 차트도 모든 막대에 값 표시")
    print()
    print("  3) 한국 종목도 다시 확인 (기존 동작 영향 없는지)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
