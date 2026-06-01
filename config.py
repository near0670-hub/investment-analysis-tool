"""
config.py — 전역 설정

모든 임계값, 섹터 매핑, Peer 그룹, PEG 기준을 여기에 모읍니다.
임계값 변경 시 이 파일만 수정하면 됩니다 (코드 곳곳에 박지 않도록).
"""

import os
from pathlib import Path

# ============================================================
# .env 자동 로드 (있을 때만)
# ============================================================
def _load_env_file():
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass  # .env 로드 실패해도 앱은 동작

_load_env_file()

# ============================================================
# 경로
# ============================================================
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_TTL_HOURS = 24  # 하루치 캐싱 (yfinance 부하 방지)

# ============================================================
# CAN SLIM 정량 체크리스트 임계값
# (PDF 기준 + 정성 항목 N/L/I/M 제외)
# ============================================================
CAN_SLIM_THRESHOLDS = {
    # C - Current Quarterly Earnings
    "C_quarterly_eps_yoy": 0.25,        # 분기 EPS YoY ≥ +25%
    "C_quarterly_revenue_yoy": 0.25,    # 분기 매출 YoY ≥ +25%
    "C_growth_acceleration": True,      # 직전분기 < 당분기 (가속 여부)
    "C_forward_eps_yoy": 0.25,          # 향후 1~2분기 예상 YoY ≥ +25% (미국/한국수동)

    # A - Annual EPS
    "A_annual_eps_cagr_3y": 0.25,       # 3년 EPS CAGR ≥ +25%
    "A_roe": 0.17,                      # ROE ≥ 17%
    "A_net_income_all_time_high": True, # 최근 1년 순이익 사상 최고치

    # S - Supply (자사주 매입 → 유통주식수 감소)
    "S_shares_outstanding_yoy_change": 0.0,  # 변화율 ≤ 0 (감소면 ✓)
}

# CAN SLIM 항목별 표시명 (한국어)
CAN_SLIM_LABELS = {
    "C_quarterly_eps_yoy":        "C: 분기 EPS YoY ≥ +25%",
    "C_quarterly_revenue_yoy":    "C: 분기 매출 YoY ≥ +25%",
    "C_growth_acceleration":      "C: 성장률 가속 (직전 분기 < 당분기)",
    "C_forward_eps_yoy":          "C: 향후 1~2분기 EPS 예상 YoY ≥ +25%",
    "A_annual_eps_cagr_3y":       "A: 3년 EPS CAGR ≥ +25%",
    "A_roe":                      "A: ROE ≥ 17%",
    "A_net_income_all_time_high": "A: 최근 1년 순이익 사상 최고치",
    "S_shares_outstanding_yoy_change": "S: 유통주식수 감소 (자사주 효과)",
}

# ============================================================
# PEG 판정 기준
# ============================================================
PEG_THRESHOLDS = {
    "very_attractive": 0.5,    # PEG < 0.5 → ✓✓
    "attractive":      1.0,    # 0.5 ≤ PEG < 1.0 → ✓
    "neutral":         1.5,    # 1.0 ≤ PEG < 1.5 → △
    "expensive":       2.0,    # 1.5 ≤ PEG < 2.0 → ⚠
                               # PEG ≥ 2.0 → ✗
}

# PEG Trap Detection 룰
PEG_TRAP_RULES = {
    "growth_too_high":        0.50,   # 성장률 50% 초과 → 신뢰성 의심
    "revenue_eps_gap":        0.20,   # 매출-EPS 갭 20%p 초과 → 일회성 의심
    "buyback_contribution":   0.30,   # 자사주 EPS 기여도 30% 초과
    "min_growth_for_peg":     0.05,   # 5% 미만이면 PEG 의미 없음
}

# ============================================================
# 밸류에이션 - 기타
# ============================================================
VALUATION_THRESHOLDS = {
    "coe_default":            0.10,   # 자기자본비용 기본값 (10%)
    "forward_per_peer_ratio": 1.20,   # 업종 중앙값 × 1.2 이내면 ✓
    "ev_ebitda_peer_max":     1.20,   # 업종 중앙값 × 1.2 이내면 ✓
}

# ============================================================
# 수익성 - DuPont 주도형 판정
# ============================================================
DUPONT_THRESHOLDS = {
    "margin_driven_min":       0.50,   # 순이익률 기여도 ≥ 50% → "마진 주도형 ★"
    "efficiency_driven_min":   0.50,   # 자산회전율 기여도 ≥ 50% → "효율성 주도형"
    "leverage_driven_warning": 0.60,   # 레버리지 기여도 ≥ 60% → "레버리지 의존형 ⚠"
    "max_leverage_safe":       2.5,    # 재무레버리지 2.5배 이하 안전
}

# DuPont 분해 베이스라인 (산업 중립 평균 가정)
# 실제 기업의 NPM/AT/Lev가 이 베이스라인 대비 얼마나 떨어져 있는지로 ROE 기여도 계산
DUPONT_BASELINE = {
    "net_margin":     0.08,   # 8% (모든 산업 평균)
    "asset_turnover": 1.0,
    "leverage":       1.5,
}

# ============================================================
# 재무안정성 임계값
# ============================================================
STABILITY_THRESHOLDS = {
    "debt_to_equity_max":     2.0,    # 부채비율 200% 이하
    "current_ratio_min":      1.0,    # 유동비율 100% 이상
    "quick_ratio_min":        0.8,    # 당좌비율 80% 이상
    "interest_coverage_min":  3.0,    # 이자보상배율 3배 이상
    "net_debt_ebitda_max":    3.0,    # 순차입금/EBITDA 3배 이하
    "altman_z_safe":          2.99,   # Altman Z 2.99 이상 안전 / 1.81 이하 위험
    "altman_z_distress":      1.81,
}

# ============================================================
# Earnings Quality (이익의 질) 임계값
# ============================================================
EARNINGS_QUALITY_THRESHOLDS = {
    "cash_conversion_min":    0.80,   # 영업CF/순이익 ≥ 0.8
    "fcf_margin_min":         0.10,   # FCF Margin ≥ 10% (성숙기업)
    "fcf_to_ni_min":          0.70,   # FCF/순이익 ≥ 0.7
    "accruals_ratio_max":     0.05,   # Accruals < 5% (낮을수록 좋음)
    "dso_warning_yoy":        0.20,   # DSO YoY +20% 이상 증가 → 경고
    "dio_warning_yoy":        0.20,   # DIO YoY +20% 이상 증가 → 경고
    "inventory_vs_revenue":   0.15,   # 재고 YoY가 매출 YoY보다 15%p 초과 → 경고
}

# ============================================================
# Capital Allocation 임계값
# ============================================================
CAPITAL_ALLOCATION_THRESHOLDS = {
    "growth_reinvestment_min":  0.50,   # 재투자 비중 ≥ 50% → "성장 재투자형"
    "shareholder_return_min":   0.70,   # 배당+자사주 비중 ≥ 70% → "주주환원형"
    "cash_hoarding_min":        0.70,   # 사내유보 ≥ 70% → "현금축적형 ⚠"
    "dividend_payout_warning":  0.80,   # 배당성향 ≥ 80% → 배당 지속가능성 위험
    "roic_min_good":            0.10,   # ROIC ≥ 10% (자본 효율 양호)
    "roic_wacc_spread_min":     0.0,    # ROIC > WACC (가치 창출)
    "wacc_default":             0.09,   # WACC 기본값 (9%) — Phase 2에서 세분화
}

# ============================================================
# 섹터 분류 — yfinance sector/industry → 내부 카테고리 매핑
# ============================================================
INTERNAL_SECTORS = [
    "TECH_AI_INFRA",
    "SEMICONDUCTOR_MEM",
    "SOFTWARE_SAAS",
    "CONSUMER_BRAND",
    "COSMETICS",
    "EV_BATTERY",
    "PLATFORM_INTERNET",
    "FINANCIAL",
    "PHARMA_BIO",
    "INDUSTRIAL_HEAVY",
    "OTHER",
]

# yfinance sector/industry 키워드 매칭 룰
# (sector_classifier.py가 이걸 사용)
SECTOR_KEYWORD_RULES = {
    "TECH_AI_INFRA": {
        "industry_keywords": ["semiconductor", "semiconductors"],
        "ticker_overrides": ["NVDA", "AMD", "AVGO", "TSM", "ASML", "MRVL", "ARM"],
    },
    "SEMICONDUCTOR_MEM": {
        "industry_keywords": [],
        "ticker_overrides": ["MU", "005930.KS", "000660.KS"],  # Micron, 삼성전자, SK하이닉스
    },
    "SOFTWARE_SAAS": {
        "industry_keywords": ["software", "application", "infrastructure software"],
        "ticker_overrides": ["MSFT", "CRM", "ADBE", "NOW", "SNOW", "DDOG"],
    },
    "CONSUMER_BRAND": {
        "industry_keywords": ["packaged foods", "beverages", "apparel", "footwear", "restaurants"],
        "ticker_overrides": ["NKE", "LULU", "SBUX", "MCD", "003230.KS"],  # 삼양식품
    },
    "COSMETICS": {
        "industry_keywords": ["household & personal products"],
        "ticker_overrides": ["EL", "ELF", "090430.KS", "278470.KS"],  # 아모레, 에이피알
    },
    "EV_BATTERY": {
        "industry_keywords": ["auto manufacturers"],
        "ticker_overrides": ["TSLA", "RIVN", "LCID", "373220.KS", "006400.KS"],  # LG엔솔, 삼성SDI
    },
    "PLATFORM_INTERNET": {
        "industry_keywords": ["internet content & information"],
        "ticker_overrides": ["GOOGL", "GOOG", "META", "035420.KS", "035720.KS"],  # 네이버, 카카오
    },
    "FINANCIAL": {
        "industry_keywords": ["banks", "insurance", "capital markets", "asset management"],
        "ticker_overrides": ["JPM", "BAC", "GS", "105560.KS", "055550.KS"],  # KB금융, 신한지주
    },
    "PHARMA_BIO": {
        "industry_keywords": ["drug manufacturers", "biotechnology", "medical"],
        "ticker_overrides": ["LLY", "NVO", "PFE", "207940.KS", "068270.KS"],  # 삼성바이오, 셀트리온
    },
    "INDUSTRIAL_HEAVY": {
        "industry_keywords": ["farm & heavy construction", "specialty industrial", "aerospace"],
        "ticker_overrides": ["CAT", "DE", "005380.KS", "329180.KS"],  # 현대차, HD현대중공업
    },
}

# 섹터별 표시명 (한국어)
SECTOR_DISPLAY_NAMES = {
    "TECH_AI_INFRA":     "반도체 / AI 인프라",
    "SEMICONDUCTOR_MEM": "반도체 메모리",
    "SOFTWARE_SAAS":     "소프트웨어 / SaaS",
    "CONSUMER_BRAND":    "소비재 브랜드",
    "COSMETICS":         "화장품",
    "EV_BATTERY":        "전기차 / 배터리",
    "PLATFORM_INTERNET": "플랫폼 / 인터넷",
    "FINANCIAL":         "금융",
    "PHARMA_BIO":        "제약 / 바이오",
    "INDUSTRIAL_HEAVY":  "중공업 / 산업재",
    "OTHER":             "기타",
}

# ============================================================
# Peer Comparison 기본 그룹
# 사용자가 추가 입력 가능 (config 기본 + UI 추가)
# ============================================================
DEFAULT_PEER_GROUPS = {
    "TECH_AI_INFRA":     ["NVDA", "AMD", "AVGO", "TSM", "ASML", "MRVL"],
    "SEMICONDUCTOR_MEM": ["MU", "005930.KS", "000660.KS"],
    "SOFTWARE_SAAS":     ["MSFT", "CRM", "ADBE", "NOW", "SNOW"],
    "CONSUMER_BRAND":    ["NKE", "LULU", "SBUX", "MCD", "003230.KS"],
    "COSMETICS":         ["EL", "ELF", "090430.KS", "278470.KS"],
    "EV_BATTERY":        ["TSLA", "RIVN", "373220.KS", "006400.KS"],
    "PLATFORM_INTERNET": ["GOOGL", "META", "035420.KS", "035720.KS"],
    "FINANCIAL":         ["JPM", "BAC", "GS", "105560.KS", "055550.KS"],
    "PHARMA_BIO":        ["LLY", "NVO", "PFE", "207940.KS", "068270.KS"],
    "INDUSTRIAL_HEAVY":  ["CAT", "DE", "005380.KS", "329180.KS"],
    "OTHER":             [],
}

# ============================================================
# 섹터별 특화 지표 가중치 / 임계값
# ============================================================
SECTOR_SPECIFIC_METRICS = {
    "TECH_AI_INFRA": {
        "key_metrics": [
            "datacenter_revenue_pct",     # 데이터센터 매출 비중
            "datacenter_revenue_yoy",     # DC 매출 YoY
            "inventory_turnover_days",    # 재고회전일수
            "capex_to_revenue",           # CapEx/매출
            "gross_margin",
        ],
        "thresholds": {
            "datacenter_yoy_strong": 0.50,
            "gross_margin_strong":   0.55,
            "capex_to_revenue_high": 0.20,
        },
    },
    "CONSUMER_BRAND": {
        "key_metrics": [
            "gross_margin",
            "advertising_to_revenue",
            "international_revenue_pct",
            "pricing_power",            # GPM YoY 변화로 추정
        ],
        "thresholds": {
            "gross_margin_strong":     0.40,
            "intl_revenue_yoy_strong": 0.20,
        },
    },
    "SOFTWARE_SAAS": {
        "key_metrics": [
            "gross_margin",
            "rd_to_revenue",
            "rule_of_40",   # 매출성장률 + 영업이익률
            "operating_margin",
        ],
        "thresholds": {
            "gross_margin_strong": 0.70,
            "rule_of_40_strong":   0.40,
        },
    },
}

# ============================================================
# Macro Context — FRED 시리즈 ID
# ============================================================
FRED_SERIES = {
    "us_10y_yield":  "DGS10",        # 미국 10년 국채 수익률
    "us_2y_yield":   "DGS2",
    "fed_funds":     "DFF",          # 연준 기준금리
    "usd_krw":       "DEXKOUS",      # USD/KRW
    "wti_crude":     "DCOILWTICO",
    "vix":           "VIXCLS",
    "sp500":         "SP500",
}

# FRED API 키 (환경변수에서 로드)
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# ============================================================
# DART (한국 공시) - https://opendart.fss.or.kr
# 환경변수 DART_API_KEY 또는 .env에 저장 권장
# ============================================================
DART_API_KEY = os.environ.get("DART_API_KEY", "")

# DART 재무제표 코드 매핑 (yfinance 형식과 통일하기 위한 매핑)
DART_FS_DIV = {
    "CFS": "연결재무제표",
    "OFS": "별도재무제표",
}
DART_DEFAULT_FS_DIV = "CFS"  # 연결재무제표 우선

# DART 보고서 코드
DART_REPORT_CODES = {
    "Q1":  "11013",  # 1분기보고서
    "Q2":  "11012",  # 반기보고서
    "Q3":  "11014",  # 3분기보고서
    "Q4":  "11011",  # 사업보고서 (연간)
}

# ============================================================
# pykrx (한국거래소) 설정
# ============================================================
PYKRX_DEFAULT_LOOKBACK_DAYS = 90  # 외국인/기관 매매 기본 조회 기간

# ============================================================
# 데이터 소스 라우팅 정책
# ============================================================
DATA_SOURCE_ROUTING = {
    "US": {
        "primary": "yfinance",
        "secondary": [],
    },
    "KR": {
        "primary": "yfinance",      # 가격, 시총, 기본정보
        "secondary": ["dart", "pykrx"],  # 재무제표 보강, 수급
    },
    "OTHER": {
        "primary": "yfinance",
        "secondary": [],
    },
}

# ============================================================
# UI / 표시
# ============================================================
VERDICT_SYMBOLS = {
    "very_good": "✓✓",
    "good":      "✓",
    "neutral":   "△",
    "warning":   "⚠",
    "bad":       "✗",
    "na":        "—",
}

# 한국 종목 ticker 패턴
KOREA_TICKER_SUFFIXES = (".KS", ".KQ")  # KOSPI, KOSDAQ

# ============================================================
# 결측치 처리 정책
# ============================================================
MISSING_DATA_POLICY = {
    "skip_if_missing": [
        "C_forward_eps_yoy",  # Forward 데이터는 없으면 스킵 (NA)
    ],
    "warn_threshold": 0.30,    # 결측치 비율 30% 초과면 경고 표시
}
