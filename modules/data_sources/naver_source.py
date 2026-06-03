"""
modules/data_sources/naver_source.py — 네이버 증권 크롤링 (v2)

네이버 금융의 '기업실적분석' 테이블 파싱.
URL: https://finance.naver.com/item/main.naver?code={6digit}

테이블 구조 (확인됨):
- Header Row 0: ['주요재무정보', '최근연간실적', '최근분기실적']  # 그룹
- Header Row 1: ['2023.12', '2024.12', '2025.12', '2026.12(E)',   # 연간 4개
                 '2025.03', '2025.06', '2025.09', '2025.12', '2026.03', '2026.06(E)']  # 분기 6개
- Body: 16개 행 (매출액, 영업이익, ..., EPS, ROE, PER, PBR 등)

단위:
- 매출액/영업이익/당기순이익: 억원
- EPS/BPS/주당배당금: 원
- 비율(영업이익률/ROE 등): %

⚠️ 주의사항:
1. 네이버 이용약관 회색지대 - 개인 학습 용도만
2. Rate limiting: 1초당 1회
3. HTML 구조 바뀌면 graceful degradation (None 반환)
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
REQUEST_TIMEOUT = 10
MIN_INTERVAL_SECONDS = 1.0

# 네이버 행 이름 → 표준 항목 매핑
ROW_NAME_MAPPING = {
    "매출액":              "Total Revenue",
    "영업이익":            "Operating Income",
    "당기순이익":          "Net Income",
    "영업이익률":          "Operating Margin",
    "순이익률":            "Net Margin",
    "ROE(지배주주)":       "ROE",
    "부채비율":            "Debt to Equity",
    "당좌비율":            "Quick Ratio",
    "유보율":              "Retained Earnings Ratio",
    "EPS(원)":             "EPS Naver",
    "PER(배)":             "PER Naver",
    "BPS(원)":             "BPS Naver",
    "PBR(배)":             "PBR Naver",
    "주당배당금(원)":      "DPS",
    "시가배당률(%)":       "Dividend Yield",
    "배당성향(%)":         "Payout Ratio",
}

# 단위 변환 (네이버 단위 → 원 단위)
ROW_UNIT_SCALE = {
    "Total Revenue":    1e8,    # 억원 → 원
    "Operating Income": 1e8,
    "Net Income":       1e8,
    # 나머지는 % 또는 원 그대로
}

_last_request_time: float = 0.0


# ============================================================
# 메인 함수
# ============================================================
def fetch_naver_consensus(ticker_6digit: str) -> Optional[dict]:
    """
    네이버 증권에서 기업실적분석 테이블 가져오기.

    Args:
        ticker_6digit: 6자리 종목코드 (예: "005930")

    Returns:
        성공:
        {
            "quarterly":         pd.DataFrame,  # 행=항목, 열=분기말 일자
            "annual":            pd.DataFrame,  # 행=항목, 열=연간 일자
            "future_periods":    list[str],     # (E) 라벨이 붙은 기간들
            "raw_quarterly_labels": list[str],  # 원본 분기 라벨 (디버그용)
            "raw_annual_labels":   list[str],
            "source":            "naver",
        }
        실패: None
    """
    if not ticker_6digit or not re.fullmatch(r"\d{6}", ticker_6digit):
        return None

    _rate_limit()

    html = _fetch_page(ticker_6digit)
    if html is None:
        return None

    return _parse_earnings_table(html)


# ============================================================
# Rate limit
# ============================================================
def _rate_limit():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - elapsed)
    _last_request_time = time.time()


# ============================================================
# HTTP 요청
# ============================================================
def _fetch_page(ticker_6digit: str) -> Optional[str]:
    url = NAVER_FINANCE_URL.format(code=ticker_6digit)
    try:
        response = requests.get(
            url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        # 네이버는 UTF-8 (apparent_encoding이 정확하게 감지)
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text
    except (requests.RequestException, requests.Timeout):
        return None


# ============================================================
# HTML 파싱 — 핵심
# ============================================================
def _parse_earnings_table(html: str) -> Optional[dict]:
    """기업실적분석 테이블 정확 파싱."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    # 1) 기업실적분석 테이블 찾기
    target_table = None
    for t in soup.find_all("table"):
        summary = t.get("summary", "")
        caption = t.find("caption")
        caption_text = caption.get_text(strip=True) if caption else ""
        if "기업실적분석" in summary or "기업실적분석" in caption_text:
            target_table = t
            break

    if target_table is None:
        return None

    # 2) 헤더에서 기간 라벨 추출 (Row 1)
    period_labels = _extract_period_labels(target_table)
    if not period_labels or len(period_labels) < 4:
        return None

    # 3) 그룹 헤더 (Row 0)로 연간/분기 경계 식별
    annual_count, quarterly_count = _identify_group_split(target_table, len(period_labels))
    if annual_count == 0 and quarterly_count == 0:
        # 그룹 헤더 못 찾으면 기본값: 처음 4개 연간, 나머지 분기
        annual_count = 4
        quarterly_count = len(period_labels) - annual_count

    annual_labels = period_labels[:annual_count]
    quarterly_labels = period_labels[annual_count:annual_count + quarterly_count]

    # 4) 데이터 행 추출
    rows_data = _extract_data_rows(target_table)
    if not rows_data:
        return None

    # 5) DataFrame 생성 (연간/분기 분리)
    annual_df = _build_dataframe(rows_data, annual_labels, slice(0, annual_count))
    quarterly_df = _build_dataframe(
        rows_data, quarterly_labels,
        slice(annual_count, annual_count + quarterly_count)
    )

    # 6) 미래 기간 (E) 식별
    future_periods = [
        lbl for lbl in (annual_labels + quarterly_labels)
        if "(E)" in lbl or "(P)" in lbl
    ]

    return {
        "quarterly": quarterly_df,
        "annual": annual_df,
        "future_periods": future_periods,
        "raw_quarterly_labels": quarterly_labels,
        "raw_annual_labels": annual_labels,
        "source": "naver",
    }


# ============================================================
# 헤더 파싱
# ============================================================
def _extract_period_labels(table) -> list[str]:
    """thead Row 1에서 기간 라벨 추출 ('2025.06', '2026.06(E)' 등)."""
    thead = table.find("thead")
    if thead is None:
        return []

    rows = thead.find_all("tr")
    # Row 0: 그룹 헤더, Row 1: 기간 라벨, Row 2: IFRS 연결
    if len(rows) < 2:
        return []

    period_row = rows[1]
    labels = []
    for th in period_row.find_all(["th", "td"]):
        text = th.get_text(strip=True)
        text = re.sub(r"\s+", "", text)
        if text:
            labels.append(text)
    return labels


def _identify_group_split(table, total_periods: int) -> tuple[int, int]:
    """
    Row 0의 그룹 헤더 ('최근연간실적', '최근분기실적')를 분석해서
    연간 컬럼 수와 분기 컬럼 수를 식별.

    Returns:
        (annual_count, quarterly_count)
    """
    thead = table.find("thead")
    if thead is None:
        return (0, 0)

    rows = thead.find_all("tr")
    if len(rows) < 1:
        return (0, 0)

    group_row = rows[0]
    annual_count = 0
    quarterly_count = 0

    for th in group_row.find_all(["th", "td"]):
        text = th.get_text(strip=True).replace(" ", "").replace("\n", "")
        colspan = int(th.get("colspan", 1) or 1)
        if "연간" in text:
            annual_count = colspan
        elif "분기" in text:
            quarterly_count = colspan

    return (annual_count, quarterly_count)


# ============================================================
# 데이터 행 추출
# ============================================================
def _extract_data_rows(table) -> dict[str, list]:
    """tbody에서 각 행의 [row_name → 값 리스트] 추출."""
    tbody = table.find("tbody")
    if tbody is None:
        return {}

    rows_data = {}
    for tr in tbody.find_all("tr"):
        th = tr.find("th")
        if th is None:
            continue
        row_name = th.get_text(strip=True)
        row_name = re.sub(r"\s+", "", row_name)

        cells = []
        for td in tr.find_all("td"):
            text = td.get_text(strip=True)
            cells.append(_parse_number(text))
        if cells:
            rows_data[row_name] = cells

    return rows_data


def _parse_number(text: str) -> Optional[float]:
    """'1,234.5' 또는 '-12,517' → float. 빈 값/'-' → None."""
    text = text.strip().replace(",", "").replace(" ", "")
    if not text or text in ("-", "N/A", "n/a"):
        return None
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    text = text.rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


# ============================================================
# DataFrame 빌드
# ============================================================
def _build_dataframe(
    rows_data: dict, period_labels: list[str], cell_slice: slice
) -> pd.DataFrame:
    """
    rows_data의 각 행에서 cell_slice 부분만 잘라서 DataFrame 만들기.
    행 이름은 ROW_NAME_MAPPING으로 영문 표준화.
    매출/이익은 억원 → 원으로 단위 변환.

    Returns:
        DataFrame (행=표준 항목명, 열=Timestamp)
    """
    if not period_labels or not rows_data:
        return pd.DataFrame()

    # 라벨을 Timestamp로 변환
    col_timestamps = [_label_to_timestamp(lbl) for lbl in period_labels]
    valid_idx = [i for i, ts in enumerate(col_timestamps) if ts is not None]
    if not valid_idx:
        return pd.DataFrame()

    valid_cols = [col_timestamps[i] for i in valid_idx]

    # 결과 빌드
    result_rows = {}
    for naver_name, values in rows_data.items():
        # 표준 이름 찾기
        std_name = ROW_NAME_MAPPING.get(naver_name)
        if std_name is None:
            continue

        # cell_slice 적용
        sliced = values[cell_slice]
        if len(sliced) != len(period_labels):
            # 컬럼 수 불일치 → skip
            continue

        # valid_idx에 해당하는 값만 + 단위 변환
        scale = ROW_UNIT_SCALE.get(std_name, 1.0)
        row_values = []
        for i in valid_idx:
            v = sliced[i]
            if v is not None:
                row_values.append(v * scale)
            else:
                row_values.append(None)
        result_rows[std_name] = row_values

    if not result_rows:
        return pd.DataFrame()

    df = pd.DataFrame(result_rows, index=valid_cols).T
    return df


def _label_to_timestamp(label: str) -> Optional[pd.Timestamp]:
    """
    '2025.06' → 2025-06-30 (분기말)
    '2026.12(E)' → 2026-12-31
    """
    # (E), (P) 제거
    clean = re.sub(r"\([EP]\)", "", label).strip()
    # YYYY.MM 형식
    m = re.match(r"^(\d{4})\.(\d{2})$", clean)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2))

    # 월별 마지막 날
    if month in (3, 12):
        # 3월: 31일, 12월: 31일
        last_day = 31
    elif month in (6, 9):
        last_day = 30
    elif month == 2:
        last_day = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
    else:
        last_day = 30

    try:
        return pd.Timestamp(f"{year}-{month:02d}-{last_day:02d}")
    except (ValueError, TypeError):
        return None
