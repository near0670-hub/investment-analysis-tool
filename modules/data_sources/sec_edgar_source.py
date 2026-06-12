"""
modules/data_sources/sec_edgar_source.py — SEC EDGAR XBRL 분기 데이터 보강

목적:
    yfinance가 5분기만 반환하는 한계 해결. SEC EDGAR Company Facts API로
    10년 이상의 분기 데이터에 직접 접근하여 YoY 계산용 8~12분기 확보.

핵심 함수:
    fetch_sec_edgar_quarterly(ticker, n_quarters=12, verbose=False) -> dict

API 사용:
    - https://www.sec.gov/files/company_tickers.json  (ticker → CIK 매핑)
    - https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
    - 무료, User-Agent 헤더 필수, ~10 req/sec rate limit

XBRL 분기 추출 전략:
    1. 10-Q에서 `fp: Q1/Q2/Q3` → 분기 단독값
    2. 10-K에서 `fp: FY`는 연간값
    3. Q4 단독값 = FY - (Q1 + Q2 + Q3) 계산
    4. 회사마다 Revenue concept 다름 (Revenues / RevenueFromContractWith...)
       → 우선순위 리스트로 fallback

캐시:
    CIK 매핑은 .cache/sec_cik_map.json 로 한 번만 다운로드
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests


# ============================================================
# 상수
# ============================================================
SEC_USER_AGENT = "InvestmentAnalysisTool near0670@gmail.com"
# ↑ SEC 가이드: 본인 도구명 + 연락처. 실제 작업용 이메일로 바꿔도 됨.

CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

CACHE_DIR = Path(".cache")
CIK_CACHE_FILE = CACHE_DIR / "sec_cik_map.json"
CIK_CACHE_TTL_DAYS = 30   # CIK 매핑은 거의 안 바뀜
FACTS_CACHE_TTL_HOURS = 24  # 분기 데이터는 하루에 한 번 갱신


# Revenue concept 우선순위 (회사마다 다른 라벨 사용)
REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",  # Apple, 신규 ASC 606
    "Revenues",                                              # NVDA, Microsoft, 일반
    "SalesRevenueNet",                                       # 구버전
    "SalesRevenueGoodsNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]

NET_INCOME_CONCEPTS = [
    "NetIncomeLoss",
    "ProfitLoss",
]

EPS_DILUTED_CONCEPTS = [
    "EarningsPerShareDiluted",
    "IncomeLossFromContinuingOperationsPerDilutedShare",
]


# ============================================================
# HTTP helpers
# ============================================================
def _http_get(url: str, verbose: bool = False) -> Optional[dict]:
    """SEC API 호출 (rate limit 안전, User-Agent 포함)."""
    headers = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 429:
            if verbose:
                print(f"  [SEC] rate limited, sleeping 2s")
            time.sleep(2)
            resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            if verbose:
                print(f"  [SEC] HTTP {resp.status_code} for {url}")
            return None
        return resp.json()
    except Exception as e:
        if verbose:
            print(f"  [SEC error] {e}")
        return None


# ============================================================
# CIK 매핑 (ticker → CIK)
# ============================================================
def _load_cik_map_cache() -> Optional[dict]:
    if not CIK_CACHE_FILE.exists():
        return None
    age_days = (time.time() - CIK_CACHE_FILE.stat().st_mtime) / 86400
    if age_days > CIK_CACHE_TTL_DAYS:
        return None
    try:
        with open(CIK_CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cik_map_cache(data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(CIK_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def get_cik_for_ticker(ticker: str, verbose: bool = False) -> Optional[str]:
    """
    Ticker → CIK (10자리 0-padded 문자열).

    SEC company_tickers.json 구조:
        {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
            ...
        }
    """
    cache = _load_cik_map_cache()
    if cache is None:
        if verbose:
            print(f"  [SEC] fetching CIK map from SEC...")
        data = _http_get(CIK_MAP_URL, verbose=verbose)
        if data is None:
            return None
        # ticker → CIK dict로 변환 (search 빠르게)
        ticker_to_cik = {}
        for entry in data.values():
            t = str(entry.get("ticker", "")).upper()
            cik = entry.get("cik_str")
            if t and cik:
                ticker_to_cik[t] = str(cik).zfill(10)
        cache = ticker_to_cik
        _save_cik_map_cache(cache)
        if verbose:
            print(f"  [SEC] CIK map cached ({len(cache)} entries)")

    ticker_upper = ticker.upper().replace(".KS", "").replace(".KQ", "")
    return cache.get(ticker_upper)


# ============================================================
# Company Facts API
# ============================================================
def _facts_cache_file(cik: str) -> Path:
    return CACHE_DIR / f"sec_facts_{cik}.json"


def _load_facts_cache(cik: str) -> Optional[dict]:
    f = _facts_cache_file(cik)
    if not f.exists():
        return None
    age_hours = (time.time() - f.stat().st_mtime) / 3600
    if age_hours > FACTS_CACHE_TTL_HOURS:
        return None
    try:
        with open(f, "r") as fp:
            return json.load(fp)
    except Exception:
        return None


def _save_facts_cache(cik: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(_facts_cache_file(cik), "w") as fp:
            json.dump(data, fp)
    except Exception:
        pass


def fetch_company_facts(cik: str, verbose: bool = False) -> Optional[dict]:
    """
    SEC EDGAR Company Facts API 호출 (캐시).

    Returns:
        {
            "cik": int,
            "entityName": str,
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "label": "Revenues",
                        "units": {"USD": [{...individual filings...}]}
                    },
                    ...
                }
            }
        }
    """
    cached = _load_facts_cache(cik)
    if cached is not None:
        if verbose:
            print(f"  [SEC] facts cache hit for CIK {cik}")
        return cached

    url = COMPANY_FACTS_URL.format(cik=cik)
    if verbose:
        print(f"  [SEC] fetching facts for CIK {cik}")
    data = _http_get(url, verbose=verbose)
    if data is None:
        return None
    _save_facts_cache(cik, data)
    return data


# ============================================================
# 분기 데이터 추출
# ============================================================
def _extract_concept_filings(facts: dict, concept_names: list[str]) -> list[dict]:
    """
    우선순위 리스트에서 첫 매칭 concept의 모든 filings 반환.

    각 filing: {
        "end": "2024-09-28",     # 보고 기간 종료일
        "val": 94930000000,
        "accn": "0000320193-...", # accession number
        "fy": 2024,
        "fp": "Q4",              # Q1/Q2/Q3/FY
        "form": "10-K",          # 10-K, 10-Q, 10-K/A, ...
        "filed": "2024-11-01",
        "frame": "CY2024Q3"       # optional (calendar year 표준화)
    }
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in concept_names:
        if concept not in us_gaap:
            continue
        units = us_gaap[concept].get("units", {})
        # USD 우선, 없으면 USD/shares (EPS는 이거)
        for unit_key in ["USD", "USD/shares"]:
            if unit_key in units:
                return units[unit_key]
        # 그래도 없으면 첫 unit
        if units:
            first_key = next(iter(units))
            return units[first_key]
    return []


def _quarterly_singles(filings: list[dict]) -> dict:
    """
    분기 단독값 추출 (3개월 분기).

    전략:
        1. 10-Q에서 fp=Q1/Q2/Q3 → 단독 분기값 (period 길이 ~3개월)
        2. 10-K에서 fp=FY → 연간값
        3. Q4 단독 = FY - (Q1 + Q2 + Q3) 계산

    Returns:
        {pd.Timestamp(period_end): float, ...}
        Q1~Q4 모두 단독 분기값
    """
    # 1) Q1/Q2/Q3 단독 분기값 (10-Q에서)
    quarterly_singles = {}   # {(fy, fp): value, period_end}
    annual_full = {}          # {fy: (value, period_end)}

    for f in filings:
        val = f.get("val")
        end = f.get("end")
        fp = f.get("fp")
        fy = f.get("fy")
        form = f.get("form", "")
        if val is None or end is None or fp is None or fy is None:
            continue

        # 수정본은 원본 우선 (수정본 형태 더 신뢰 가능하지만 일관성 위해 첫 보고 사용)
        # form: 10-Q, 10-Q/A, 10-K, 10-K/A
        # /A (amendment) 은 가장 마지막에 처리하므로 정렬

        # form에서 amendment 표시 분리
        is_amendment = "/A" in form
        base_form = form.replace("/A", "")

        # 분기 데이터: 10-Q의 Q1/Q2/Q3 또는 10-K의 Q1/Q2/Q3 (10-K에 Q4 분기도 있을 때)
        if fp in ("Q1", "Q2", "Q3"):
            # period 길이가 약 3개월인지 확인 (start 정보 있으면)
            start_str = f.get("start")
            if start_str:
                try:
                    days = (pd.Timestamp(end) - pd.Timestamp(start_str)).days
                    if days > 100 or days < 70:  # 3개월 분기 아님 (YTD 등)
                        continue
                except Exception:
                    pass
            key = (fy, fp)
            # 수정본은 원본보다 우선
            if key not in quarterly_singles or is_amendment:
                quarterly_singles[key] = {"val": float(val), "end": end, "form": form}

        elif fp == "FY":
            # 연간값 (10-K)
            start_str = f.get("start")
            if start_str:
                try:
                    days = (pd.Timestamp(end) - pd.Timestamp(start_str)).days
                    if days < 350 or days > 380:  # 1년 아님
                        continue
                except Exception:
                    pass
            if fy not in annual_full or is_amendment:
                annual_full[fy] = {"val": float(val), "end": end, "form": form}

    # 2) Q4 = FY - (Q1 + Q2 + Q3) 계산
    result = {}

    for (fy, fp), q in quarterly_singles.items():
        ts = pd.Timestamp(q["end"]).normalize()
        result[ts] = q["val"]

    for fy, ann in annual_full.items():
        q1 = quarterly_singles.get((fy, "Q1"))
        q2 = quarterly_singles.get((fy, "Q2"))
        q3 = quarterly_singles.get((fy, "Q3"))
        if q1 and q2 and q3:
            q4_val = ann["val"] - (q1["val"] + q2["val"] + q3["val"])
            q4_ts = pd.Timestamp(ann["end"]).normalize()
            result[q4_ts] = q4_val

    return result


def _to_yfinance_format(
    revenue_q: dict,
    net_income_q: dict,
    eps_diluted_q: dict,
    n_quarters: int = 12,
) -> pd.DataFrame:
    """
    분기 단독값 dict들을 yfinance quarterly_income_stmt 형식으로 변환.

    Returns:
        DataFrame: index=항목 라벨, columns=분기말 Timestamp (최신=좌측)
        Row labels: "Total Revenue", "Net Income", "Diluted EPS"
        (본인 timeseries.py INCOME_ROW_ALIASES와 호환되는 표준 이름 사용)
    """
    all_timestamps = set()
    for d in (revenue_q, net_income_q, eps_diluted_q):
        all_timestamps.update(d.keys())

    # 최신 순으로 정렬 후 n_quarters 만큼 자르기
    sorted_ts = sorted(all_timestamps, reverse=True)[:n_quarters]

    if not sorted_ts:
        return pd.DataFrame()

    rows = {
        "Total Revenue": [revenue_q.get(ts) for ts in sorted_ts],
        "Net Income":    [net_income_q.get(ts) for ts in sorted_ts],
        "Diluted EPS":   [eps_diluted_q.get(ts) for ts in sorted_ts],
    }
    return pd.DataFrame(rows, index=sorted_ts).T


# ============================================================
# 메인 함수
# ============================================================
def fetch_sec_edgar_quarterly(
    ticker: str,
    n_quarters: int = 12,
    verbose: bool = False,
) -> dict:
    """
    SEC EDGAR에서 미국 종목의 분기 income statement 추출.

    Args:
        ticker: 미국 종목 ticker (예: "AAPL")
        n_quarters: 반환할 최대 분기 수 (기본 12)
        verbose: 진행 로그 출력

    Returns:
        {
            "income_quarterly": pd.DataFrame,  # yfinance 호환, 빈 DF 가능
            "source": "sec_edgar",
            "cik": str | None,
            "concepts_used": dict,             # 어떤 concept 매칭됐는지
            "n_quarters": int,                 # 실제 추출된 분기 수
        }
    """
    result_empty = {
        "income_quarterly": pd.DataFrame(),
        "source": "sec_edgar",
        "cik": None,
        "concepts_used": {},
        "n_quarters": 0,
    }

    # 1) CIK 변환
    cik = get_cik_for_ticker(ticker, verbose=verbose)
    if not cik:
        if verbose:
            print(f"  [SEC] no CIK for {ticker}")
        return result_empty

    # 2) Company Facts
    facts = fetch_company_facts(cik, verbose=verbose)
    if facts is None:
        if verbose:
            print(f"  [SEC] no facts for CIK {cik}")
        return {**result_empty, "cik": cik}

    # 3) 각 concept 추출
    concepts_used = {}

    rev_filings = _extract_concept_filings(facts, REVENUE_CONCEPTS)
    if rev_filings:
        # 어떤 concept이 매칭됐는지 기록
        us_gaap = facts["facts"]["us-gaap"]
        for c in REVENUE_CONCEPTS:
            if c in us_gaap:
                concepts_used["revenue"] = c
                break
    revenue_q = _quarterly_singles(rev_filings)

    ni_filings = _extract_concept_filings(facts, NET_INCOME_CONCEPTS)
    if ni_filings:
        us_gaap = facts["facts"]["us-gaap"]
        for c in NET_INCOME_CONCEPTS:
            if c in us_gaap:
                concepts_used["net_income"] = c
                break
    net_income_q = _quarterly_singles(ni_filings)

    eps_filings = _extract_concept_filings(facts, EPS_DILUTED_CONCEPTS)
    if eps_filings:
        us_gaap = facts["facts"]["us-gaap"]
        for c in EPS_DILUTED_CONCEPTS:
            if c in us_gaap:
                concepts_used["eps_diluted"] = c
                break
    eps_diluted_q = _quarterly_singles(eps_filings)

    # 4) yfinance 형식 변환
    income_quarterly = _to_yfinance_format(
        revenue_q, net_income_q, eps_diluted_q, n_quarters=n_quarters
    )

    if verbose:
        print(f"  [SEC] {ticker} (CIK {cik}): "
              f"{len(income_quarterly.columns)} quarters extracted, "
              f"concepts={concepts_used}")

    return {
        "income_quarterly": income_quarterly,
        "source": "sec_edgar",
        "cik": cik,
        "concepts_used": concepts_used,
        "n_quarters": len(income_quarterly.columns),
    }
