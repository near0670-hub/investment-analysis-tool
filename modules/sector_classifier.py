"""
modules/sector_classifier.py — ticker → 내부 섹터 분류

분류 우선순위:
1. ticker_overrides (특정 ticker 명시)  → 가장 정확
2. yfinance industry/sector 키워드 매칭   → 일반적
3. fallback "OTHER"

이게 있어야 "이 기업에는 어떤 섹터별 분석 / Peer 그룹을 쓸지" 자동 결정.
"""

from typing import Optional

from config import (
    SECTOR_KEYWORD_RULES,
    SECTOR_DISPLAY_NAMES,
    DEFAULT_PEER_GROUPS,
)


def classify_sector(
    ticker: str,
    yf_sector: Optional[str] = None,
    yf_industry: Optional[str] = None,
) -> str:
    """
    Ticker + yfinance sector/industry 정보로 내부 섹터 결정.

    Args:
        ticker: 종목 코드 (예: "NVDA", "005930.KS")
        yf_sector: yfinance의 sector (예: "Technology")
        yf_industry: yfinance의 industry (예: "Semiconductors")

    Returns:
        내부 섹터 코드 (예: "TECH_AI_INFRA")
    """
    ticker_upper = ticker.strip().upper()

    # 1순위: ticker_overrides 매칭
    for sector_code, rule in SECTOR_KEYWORD_RULES.items():
        overrides = [t.upper() for t in rule.get("ticker_overrides", [])]
        if ticker_upper in overrides:
            return sector_code

    # 2순위: industry 키워드 매칭
    if yf_industry:
        industry_lower = yf_industry.lower()
        for sector_code, rule in SECTOR_KEYWORD_RULES.items():
            for kw in rule.get("industry_keywords", []):
                if kw.lower() in industry_lower:
                    return sector_code

    # 3순위: sector 키워드 매칭 (보조)
    if yf_sector:
        sector_lower = yf_sector.lower()
        if "technology" in sector_lower:
            return "SOFTWARE_SAAS"  # 반도체에 안 잡힌 테크는 SaaS로
        if "financial" in sector_lower:
            return "FINANCIAL"
        if "healthcare" in sector_lower:
            return "PHARMA_BIO"
        if "energy" in sector_lower:
            return "INDUSTRIAL_HEAVY"
        if "consumer" in sector_lower:
            return "CONSUMER_BRAND"
        if "communication" in sector_lower:
            return "PLATFORM_INTERNET"

    return "OTHER"


def get_sector_display_name(sector_code: str) -> str:
    """내부 섹터 코드 → 한국어 표시명"""
    return SECTOR_DISPLAY_NAMES.get(sector_code, sector_code)


def get_default_peers(sector_code: str, exclude_ticker: Optional[str] = None) -> list[str]:
    """
    섹터의 기본 Peer 그룹 반환.
    exclude_ticker로 자기 자신은 제외 가능.
    """
    peers = DEFAULT_PEER_GROUPS.get(sector_code, []).copy()
    if exclude_ticker:
        exclude_upper = exclude_ticker.strip().upper()
        peers = [p for p in peers if p.upper() != exclude_upper]
    return peers
