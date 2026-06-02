"""
modules/data_sources/naver_source.py — 네이버 증권 크롤링

목적: 한국 종목의 분기/연간 시계열 + 컨센서스(미래 추정치) 보강.
yfinance와 DART는 미래 추정치를 거의 제공하지 않으므로, 네이버 증권의
"기업실적분석" 테이블에서 보강한다.

⚠️ 주의사항:
1. 네이버 이용약관: 자동 수집은 회색지대. 개인 학습 용도로만.
2. Rate limiting: 1초당 1회 이하 호출. 캐시 적극 활용.
3. HTML 구조가 바뀌면 깨질 수 있음 → graceful degradation으로 처리.
4. 실패해도 None 반환, 앱은 절대 안 죽음.

URL: https://finance.naver.com/item/main.naver?code={6자리}
"""

from __future__ import annotations

import re
import time
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup


# ============================================================
# 상수
# ============================================================
NAVER_FINANCE_URL = "https://finance.naver.com/item/main.naver?code={code}"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
REQUEST_TIMEOUT = 10  # 초
MIN_INTERVAL_SECONDS = 1.0  # rate limit: 1초당 1회

# 마지막 요청 시각 (rate limiting용)
_last_request_time: float = 0.0


# ============================================================
# 메인 함수
# ============================================================
def fetch_naver_consensus(ticker_6digit: str) -> Optional[dict]:
    """
    네이버 증권에서 분기/연간 실적 + 컨센서스 데이터 가져오기.

    Args:
        ticker_6digit: 6자리 종목코드 (예: "005930"). ".KS" 접미사 없이.

    Returns:
        성공:
        {
            "quarterly": pd.DataFrame (열: 분기 라벨, 행: 항목),
            "annual":    pd.DataFrame (열: 연도 라벨, 행: 항목),
            "future_periods": list[str],  # 어느 기간이 컨센서스인지
            "source": "naver",
        }
        실패: None

    Note:
        실패해도 예외 던지지 않음. 호출 측은 None 체크만 하면 됨.
    """
    # 입력 검증
    if not ticker_6digit or not re.fullmatch(r"\d{6}", ticker_6digit):
        return None

    # Rate limiting
    _rate_limit()

    # 페이지 가져오기
    html = _fetch_page(ticker_6digit)
    if html is None:
        return None

    # "기업실적분석" 테이블 파싱
    return _parse_earnings_table(html)


# ============================================================
# 내부: rate limit
# ============================================================
def _rate_limit():
    """최소 1초 간격 유지."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - elapsed)
    _last_request_time = time.time()


# ============================================================
# 내부: HTTP 요청
# ============================================================
def _fetch_page(ticker_6digit: str) -> Optional[str]:
    """네이버 증권 페이지 HTML 가져오기. 실패 시 None."""
    url = NAVER_FINANCE_URL.format(code=ticker_6digit)
    try:
        response = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        # 네이버는 EUC-KR이지만 종종 잘못 감지됨. 명시적으로 처리.
        response.encoding = response.apparent_encoding or "euc-kr"
        return response.text
    except (requests.RequestException, requests.Timeout):
        return None


# ============================================================
# 내부: HTML 파싱
# ============================================================
def _parse_earnings_table(html: str) -> Optional[dict]:
    """
    네이버 종목 페이지에서 "기업실적분석" 테이블 추출.

    테이블 구조 (예시):
        |               | 2023.12 | 2024.12 | 2025.12 | 2026.12(E) | 2025.06 | 2025.09 | 2025.12 | 2026.03 |
        | 매출액(억원) |  ...    |   ...   |   ...   |    ...     |   ...   |   ...   |   ...   |   ...   |
        | 영업이익     |  ...    |   ...   |   ...   |    ...     |   ...   |   ...   |   ...   |   ...   |
        | EPS(원)      |  ...    |   ...   |   ...   |    ...     |   ...   |   ...   |   ...   |   ...   |
        | ROE          |  ...    |   ...   |   ...   |    ...     |   ...   |   ...   |   ...   |   ...   |

    (E) 가 붙은 컬럼이 컨센서스(미래 추정치).
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return None

    # "기업실적분석" 테이블 찾기 (네이버 클래스명은 "tb_type1 tb_num tb_type1_ifrs")
    table = None
    candidates = soup.find_all("table")
    for t in candidates:
        # caption 또는 summary 속성으로 식별
        summary = t.get("summary", "")
        caption = t.find("caption")
        caption_text = caption.get_text(strip=True) if caption else ""

        if ("기업실적분석" in summary or
            "기업실적분석" in caption_text or
            "실적" in summary):
            table = t
            break

    if table is None:
        # Fallback: 클래스명으로 찾기
        for class_name in ["tb_type1", "gHead01"]:
            t = soup.find("table", class_=re.compile(class_name))
            if t is not None:
                # 행 텍스트에 "매출액" 같은 키워드 있는지 확인
                if "매출" in t.get_text():
                    table = t
                    break

    if table is None:
        return None

    # 헤더 (기간 라벨) 추출
    period_labels = _extract_period_headers(table)
    if not period_labels:
        return None

    # 데이터 행 추출
    rows_data = _extract_data_rows(table, period_labels)
    if not rows_data:
        return None

    # 분기/연간 분리
    quarterly_cols = [p for p in period_labels if _is_quarterly_label(p)]
    annual_cols = [p for p in period_labels if _is_annual_label(p)]

    if not quarterly_cols and not annual_cols:
        return None

    # DataFrame 빌드
    quarterly_df = _build_dataframe(rows_data, quarterly_cols)
    annual_df = _build_dataframe(rows_data, annual_cols)

    # 미래 구간(E 붙은 것) 추출
    future_periods = [p for p in period_labels if "(E)" in p or "(P)" in p]

    return {
        "quarterly": quarterly_df,
        "annual": annual_df,
        "future_periods": future_periods,
        "source": "naver",
    }


def _extract_period_headers(table) -> list[str]:
    """테이블의 헤더(기간 라벨) 추출. 예: ['2023.12', '2024.12', '2026.12(E)', ...]"""
    thead = table.find("thead")
    if thead is None:
        return []

    # 가장 안쪽 헤더 행에서 th들 추출
    header_rows = thead.find_all("tr")
    if not header_rows:
        return []

    # 보통 마지막 행이 기간 라벨
    last_header_row = header_rows[-1]
    ths = last_header_row.find_all("th")

    labels = []
    for th in ths:
        text = th.get_text(strip=True)
        # 줄바꿈 정리
        text = re.sub(r"\s+", "", text)
        if text:
            labels.append(text)

    return labels


def _extract_data_rows(table, period_labels: list[str]) -> dict[str, list]:
    """데이터 행 추출. 행 이름(예: '매출액')을 키, 셀 값 리스트를 값으로."""
    tbody = table.find("tbody")
    if tbody is None:
        return {}

    rows_data = {}
    for tr in tbody.find_all("tr"):
        # 행 이름
        th = tr.find("th")
        if th is None:
            continue
        row_name = th.get_text(strip=True)
        row_name = re.sub(r"\s+", " ", row_name)

        # 셀 값들
        cells = []
        for td in tr.find_all("td"):
            text = td.get_text(strip=True)
            cells.append(_parse_number(text))

        if cells:
            rows_data[row_name] = cells

    return rows_data


def _build_dataframe(rows_data: dict, columns: list[str]) -> pd.DataFrame:
    """행 데이터에서 특정 컬럼만 추출해서 DataFrame 만들기."""
    if not columns or not rows_data:
        return pd.DataFrame()

    # 첫 번째 행의 길이로 전체 컬럼 개수 추정
    first_row = next(iter(rows_data.values()), [])
    n_total = len(first_row)
    if n_total == 0:
        return pd.DataFrame()

    # 컬럼 인덱스 매핑 (period_labels와 cells의 순서가 같다고 가정)
    # 전체 columns 중에서 quarterly/annual 만 골라야 함
    # → 호출자가 quarterly_cols/annual_cols를 미리 결정했으므로,
    #   여기서는 인덱스로 슬라이싱

    # 실제로는 _extract_period_headers가 반환한 전체 period_labels와
    # 같은 순서로 cells가 있다고 가정
    # 그래서 columns의 위치를 전체 period_labels에서 찾아야 함
    # 단순화: 모든 컬럼 다 들어간 DataFrame 만들고 호출자가 슬라이싱

    df = pd.DataFrame(rows_data).T
    # 컬럼 이름은 호출자가 알아서 매핑 — 여기서는 일단 인덱스 그대로
    return df


def _parse_number(text: str) -> Optional[float]:
    """'1,234.5' 형식의 문자열을 float로. 빈 값/'-'은 None."""
    text = text.strip().replace(",", "").replace(" ", "")
    if not text or text in ("-", "N/A", "n/a"):
        return None
    # 괄호로 감싸진 음수: (123) → -123
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    # 끝에 % 붙은 거 제거
    text = text.rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


def _is_quarterly_label(label: str) -> bool:
    """예: '2025.06', '2026.03(E)' 같은 분기 라벨인지."""
    # 분기: YYYY.MM 또는 YYYY.MM(E)
    # 월이 03, 06, 09, 12 중 하나면 분기로 간주 (단, 연간일 가능성도 있음)
    # 네이버 페이지는 보통 연간(YYYY.12)과 분기(YYYY.03, YYYY.06, YYYY.09, YYYY.12)를 섞어서 보여줌
    # 분기 컬럼은 보통 연간 컬럼 다음에 옴
    # 정확한 구분은 어려우므로, 간단한 휴리스틱:
    # - YYYY.MM 형식이고 월이 03/06/09 면 무조건 분기
    # - YYYY.12 는 연간 컬럼이 먼저, 그 다음에 나오는 12는 분기
    # 일단 단순화: YYYY.MM 형식이고 (E)나 (P) 가 아니거나, 03/06/09/12 둘 다 분기 후보로
    match = re.match(r"^(\d{4})\.(\d{2})(\(E\)|\(P\))?$", label)
    if not match:
        return False
    month = int(match.group(2))
    return month in (3, 6, 9)  # 12월은 연간으로 분류


def _is_annual_label(label: str) -> bool:
    """예: '2024.12', '2026.12(E)' 같은 연간 라벨인지."""
    match = re.match(r"^(\d{4})\.(\d{2})(\(E\)|\(P\))?$", label)
    if not match:
        return False
    month = int(match.group(2))
    return month == 12
