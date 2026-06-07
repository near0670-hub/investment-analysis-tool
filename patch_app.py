"""
patch_app.py — Phase 4: STABILITY 탭 통합 자동 패치 스크립트.

본인 investment_analysis_tool/ 디렉토리에서 한 번만 실행:
    python patch_app.py

수정사항 3곳:
    1. import 추가 (기존 modules import 옆)
    2. st.tabs unpacking 4개 → 5개
    3. with tab_stab: 블록 추가 (tab_profit과 tab_val 사이)

안전장치:
    - 실행 전 app.py.bak 자동 생성
    - 이미 패치되어 있으면 skip
    - 각 단계 성공/실패 출력
    - 어느 단계라도 실패하면 rollback
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

APP_FILE = Path("app.py")
BACKUP = Path("app.py.bak")


# ============================================================
# 정확한 매칭 패턴 (본인 라인 1905-1917 그대로)
# ============================================================
OLD_TABS = '''    tab_summary, tab_growth, tab_profit, tab_val = st.tabs(
        ["SUMMARY", "GROWTH", "PROFITABILITY", "VALUATION"]
    )'''

NEW_TABS = '''    tab_summary, tab_growth, tab_profit, tab_stab, tab_val = st.tabs(
        ["SUMMARY", "GROWTH", "PROFITABILITY", "STABILITY", "VALUATION"]
    )'''

OLD_WITH = '''    with tab_profit:
        render_profitability_tab(data)
    with tab_val:
        render_valuation_tab(data, user_inputs)'''

NEW_WITH = '''    with tab_profit:
        render_profitability_tab(data)
    with tab_stab:
        render_stability_tab(data)
    with tab_val:
        render_valuation_tab(data, user_inputs)'''

IMPORT_LINE = "from modules.stability_analysis import render_tab as render_stability_tab"


def main() -> int:
    if not APP_FILE.exists():
        print(f"✗ {APP_FILE} 없음. investment_analysis_tool/ 디렉토리에서 실행하세요.")
        return 1

    # 백업
    if not BACKUP.exists():
        shutil.copy(APP_FILE, BACKUP)
        print(f"✓ 백업 생성: {BACKUP}")
    else:
        print(f"⚠ {BACKUP} 이미 존재 — 덮어쓰지 않음 (원본 보존)")

    original = APP_FILE.read_text()
    text = original

    # ----- 패치 1: tabs unpacking -----
    if NEW_TABS in text:
        print("✓ [1/3] tabs unpacking — 이미 패치됨, skip")
    elif OLD_TABS in text:
        text = text.replace(OLD_TABS, NEW_TABS, 1)
        print("✓ [1/3] tabs unpacking — 4개 → 5개")
    else:
        print("✗ [1/3] tabs unpacking — 기존 패턴 못 찾음")
        print("       기대한 패턴 (라인 1905 근처):")
        print("       tab_summary, tab_growth, tab_profit, tab_val = st.tabs(...)")
        return 1

    # ----- 패치 2: with 블록 -----
    if "with tab_stab:" in text:
        print("✓ [2/3] with 블록 — 이미 패치됨, skip")
    elif OLD_WITH in text:
        text = text.replace(OLD_WITH, NEW_WITH, 1)
        print("✓ [2/3] with 블록 — tab_stab 추가")
    else:
        print("✗ [2/3] with 블록 — 기존 패턴 못 찾음")
        return 1

    # ----- 패치 3: import -----
    if IMPORT_LINE in text:
        print("✓ [3/3] import — 이미 추가됨, skip")
    else:
        # 다른 modules import 라인 찾기 (마지막 'from modules.' 라인 뒤에 삽입)
        lines = text.split("\n")
        last_modules_import_idx = None
        for i, line in enumerate(lines):
            if line.startswith("from modules.") or line.startswith("import modules."):
                last_modules_import_idx = i

        if last_modules_import_idx is None:
            # fallback: 첫 번째 import 뒤
            for i, line in enumerate(lines):
                if line.startswith("import ") or line.startswith("from "):
                    last_modules_import_idx = i

        if last_modules_import_idx is None:
            print("✗ [3/3] import — 삽입할 위치를 못 찾음")
            return 1

        lines.insert(last_modules_import_idx + 1, IMPORT_LINE)
        text = "\n".join(lines)
        print(f"✓ [3/3] import — 라인 {last_modules_import_idx + 2}에 추가")

    # ----- 변경 사항 있으면 저장 -----
    if text == original:
        print("\n→ 변경 사항 없음 (모두 이미 패치됨)")
        return 0

    APP_FILE.write_text(text)
    print(f"\n✓ {APP_FILE} 저장 완료")
    print(f"  원본은 {BACKUP} 에 보존됨")
    print("\n다음 단계:")
    print("  1) streamlit 재시작:")
    print("       pkill -f streamlit ; sleep 2 ; streamlit run app.py")
    print("  2) 브라우저 강제 새로고침: Cmd+Shift+R")
    print("  3) PROFITABILITY 옆에 STABILITY 탭 확인")
    return 0


if __name__ == "__main__":
    sys.exit(main())
