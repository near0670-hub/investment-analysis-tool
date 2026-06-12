"""
patch_step2_us_forward_integration.py — Phase 4.5 마무리

2가지 변경:
    1. yfinance_source.py: to_consensus_format() 어댑터 함수 추가
       → fetch_us_forward_consensus() 결과를 naver_source 호환 형식으로 변환
    2. data_loader.py: 한국 블록 다음에 미국 else 블록 추가
       → 미국 종목의 forward consensus 수집 + naver_data 변수 재사용

→ timeseries.py 변경 0
→ app.py 변경 0 (kr_naver_consensus 키 그대로 사용 — 미국 데이터도 자동으로 들어감)

전제:
    1단계 패치 (patch_us_forward_yfinance.py) 이미 적용된 상태
    → fetch_us_forward_consensus() 함수가 yfinance_source.py에 존재해야 함

실행:
    python patch_step2_us_forward_integration.py

안전장치:
    - 각 파일 백업 자동 생성
    - 멱등성 (두 번 실행해도 안전)
    - 1단계 적용 안 됐으면 안내 후 중단
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


YF = Path("modules/data_sources/yfinance_source.py")
DL = Path("modules/data_loader.py")
YF_BAK = Path("modules/data_sources/yfinance_source.py.bak.step2")
DL_BAK = Path("modules/data_loader.py.bak.step2")


# ============================================================
# 1. yfinance_source.py에 추가할 어댑터 함수
# ============================================================
ADAPTER_FUNCTION = '''

def to_consensus_format(us_consensus: dict) -> dict:
    """
    fetch_us_forward_consensus() 결과를 naver_source 호환 형식으로 변환.

    naver_source 형식:
        {
            "quarterly": pd.DataFrame(
                index=["Total Revenue", "EPS Naver"],
                columns=[pd.Timestamp(...), ...]  # 분기말 날짜
            ),
            "annual": pd.DataFrame(...)
        }

    이 형식으로 변환하면 modules/timeseries.py의 _get_naver_quarterly_eps/
    _get_naver_annual_eps 등 헬퍼가 그대로 동작 (변경 0).

    Args:
        us_consensus: fetch_us_forward_consensus() 반환 dict

    Returns:
        {"quarterly": DataFrame, "annual": DataFrame}
        빈 입력 → 빈 DataFrame 두 개.
    """
    def _build_df(items: list) -> pd.DataFrame:
        if not items:
            return pd.DataFrame()
        cols = {}
        for item in items:
            try:
                ts = pd.Timestamp(item["period_end"])
            except (TypeError, ValueError, KeyError):
                continue
            cols[ts] = {
                "Total Revenue": item.get("revenue_est"),
                "EPS Naver":     item.get("eps_est"),
            }
        if not cols:
            return pd.DataFrame()
        return pd.DataFrame(cols)  # columns=timestamps, index=row names

    return {
        "quarterly": _build_df(us_consensus.get("quarterly_forward", [])),
        "annual":    _build_df(us_consensus.get("annual_forward",    [])),
    }
'''


# ============================================================
# 2. data_loader.py에 추가할 미국 else 블록
# ============================================================
# 본인 line 471-474 (한국 naver 블록 끝) 다음에 삽입
OLD_DL = '''        except Exception as e:
            naver_data = None
            if verbose:
                print(f"  [naver error, gracefully skipped] {e}")

    # ============================================================
    # 5. 재무제표 병합 (한국 종목은 DART 우선)
    # ============================================================'''

NEW_DL = '''        except Exception as e:
            naver_data = None
            if verbose:
                print(f"  [naver error, gracefully skipped] {e}")

    else:
        # ============================================================
        # 미국 종목: yfinance forward consensus
        # ⚠️ 실패해도 앱 안 죽음 (graceful degradation)
        # naver_data 변수에 동일 형식으로 저장 → timeseries.py 재사용
        # ============================================================
        try:
            from modules.data_sources.yfinance_source import (
                fetch_us_forward_consensus, to_consensus_format,
            )
            us_consensus = fetch_us_forward_consensus(ticker, verbose=verbose)
            naver_data = to_consensus_format(us_consensus)
            # 빈 결과면 None (timeseries.py가 None 체크함)
            if naver_data["quarterly"].empty and naver_data["annual"].empty:
                naver_data = None
            else:
                sources_used.append("yf_consensus")
                if verbose:
                    print(f"  [yf_consensus] "
                          f"{len(us_consensus.get('quarterly_forward', []))}q, "
                          f"{len(us_consensus.get('annual_forward', []))}y")
        except Exception as e:
            naver_data = None
            if verbose:
                print(f"  [yf_consensus error, gracefully skipped] {e}")

    # ============================================================
    # 5. 재무제표 병합 (한국 종목은 DART 우선)
    # ============================================================'''


def main() -> int:
    # ============================================================
    # 사전 점검
    # ============================================================
    if not YF.exists():
        print(f"✗ {YF} 없음.")
        return 1
    if not DL.exists():
        print(f"✗ {DL} 없음.")
        return 1

    yf_text = YF.read_text()
    dl_text = DL.read_text()

    if "def fetch_us_forward_consensus" not in yf_text:
        print("✗ 1단계 패치 (fetch_us_forward_consensus) 미적용.")
        print("  먼저 patch_us_forward_yfinance.py 실행하세요.")
        return 1

    # ============================================================
    # 백업
    # ============================================================
    if not YF_BAK.exists():
        shutil.copy(YF, YF_BAK)
        print(f"✓ 백업: {YF_BAK}")
    if not DL_BAK.exists():
        shutil.copy(DL, DL_BAK)
        print(f"✓ 백업: {DL_BAK}")

    # ============================================================
    # 패치 1: yfinance_source.py에 어댑터 추가
    # ============================================================
    if "def to_consensus_format" in yf_text:
        print("✓ [1/2] yfinance_source.py 어댑터 — 이미 적용됨")
    else:
        if not yf_text.endswith("\n"):
            yf_text += "\n"
        yf_text += ADAPTER_FUNCTION
        YF.write_text(yf_text)
        print(f"✓ [1/2] yfinance_source.py — to_consensus_format() 추가")

    # ============================================================
    # 패치 2: data_loader.py에 미국 else 블록 추가
    # ============================================================
    if "    else:\n        # ============================================================\n        # 미국 종목: yfinance forward consensus" in dl_text:
        print("✓ [2/2] data_loader.py 미국 블록 — 이미 적용됨")
    elif OLD_DL in dl_text:
        dl_text = dl_text.replace(OLD_DL, NEW_DL, 1)
        DL.write_text(dl_text)
        print(f"✓ [2/2] data_loader.py — 미국 else 블록 추가")
    else:
        print("✗ [2/2] data_loader.py — 기존 한국 naver 블록 패턴 못 찾음")
        print("  본인 data_loader.py line 471-474 부근이 다를 수 있음")
        return 1

    print()
    print("=" * 60)
    print("✓ Phase 4.5 통합 완료")
    print("=" * 60)
    print()
    print("동작 확인:")
    print("  1) 캐시 청소:")
    print("       find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null")
    print("       rm -rf .cache 2>/dev/null   # 본인 캐시 경로 다르면 무시")
    print("  2) Streamlit 재시작:")
    print("       pkill -f streamlit ; sleep 2 ; streamlit run app.py")
    print("  3) AAPL 또는 NVDA 조회 → GROWTH 탭")
    print("     기대 결과:")
    print("       - QUARTERLY 표: 4 actual + 2 forward 행")
    print("       - 모든 행에 YoY 계산됨")
    print("       - forward 행은 amber 색상")
    print("       - ANNUAL 표: forward FY27 행에 Revenue + EPS 둘 다 표시")
    print("       - 91.9% 떠다니던 라벨 해결 (forward Revenue 표에 들어감)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
