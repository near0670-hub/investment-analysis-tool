# Investment Analysis Tool

시니어 주식 리서치 애널리스트 / 펀드매니저용 **Fundamental Equity Research Dashboard**.
단순 수치 나열이 아닌 **투자자 관점의 해석**을 제공하는 Python + Streamlit 기반 분석 도구.

## 핵심 특징

- 🇰🇷🇺🇸 **한국 + 미국 종목** 동시 지원
- ✅ 점수화가 아닌 **CAN SLIM 스타일 체크리스트** (정량 항목만)
- 📊 **PEG 3변형** (TTM / Forward 1Y / **Forward 2Y** 메인)
- 🔬 **DuPont 3분해** + 마진/효율/레버리지 주도형 자동 판정
- 💰 **이익의 질** + **자본배분** 분석
- 👥 **섹터별 Peer Comparison** + 버블차트
- 📅 어닝/배당 일정 + 매크로 사이드바 (펀드매니저식)
- 🚨 **Trap Detection** (밸류에이션 함정, 회계 신호, 사이클 정점)

## 분석 철학

1. **주가 = 이익 × 멀티플**
2. PER 낮다고 무조건 저평가 아님 → Trap Detection 적용
3. ROE는 DuPont 분해로 마진 / 회전율 / 레버리지 원인 규명
4. EPS 성장 > 매출 성장일 때 영업레버리지 / 비용절감 / 자사주 효과 구분
5. 섹터마다 핵심 지표가 다름 (반도체 ≠ 소비재 ≠ SaaS)

## 폴더 구조

```
investment_analysis_tool/
├── app.py                          # Streamlit 진입점
├── config.py                       # 모든 임계값, 섹터 매핑, API 키 로드
├── requirements.txt
├── README.md
├── .env.example                    # API 키 템플릿
├── .gitignore
├── data/cache/                     # 응답 캐시
│
├── modules/
│   ├── data_loader.py              # ★ 멀티 소스 라우팅 (표준 스키마 통합)
│   ├── data_sources/               # ★ 소스별 전담 모듈
│   │   ├── yfinance_source.py      # 미국 종목 전체 + 한국 기본정보
│   │   ├── dart_source.py          # 한국 공시/재무제표
│   │   └── pykrx_source.py         # 한국 수급 (외국인/기관/공매도)
│   │
│   ├── sector_classifier.py        # ticker → 내부 섹터 분류
│   │
│   # 아래는 Week 2~3에서 추가
│   ├── financial_metrics.py
│   ├── can_slim_checker.py
│   ├── growth_analysis.py
│   ├── valuation_analysis.py       # PEG 3변형 포함
│   ├── profitability_analysis.py   # DuPont
│   ├── stability_analysis.py
│   ├── earnings_quality.py
│   ├── capital_allocation.py
│   ├── calendar_tracker.py
│   ├── macro_context.py
│   ├── peer_comparison.py
│   ├── report_generator.py
│   └── sector_specific/
│       ├── semiconductor.py
│       └── consumer_brand.py
├── utils/
│   ├── formatting.py
│   ├── fx.py
│   └── validation.py
└── tests/
```

## 설치 및 실행

### 1. 가상환경 + 패키지 설치
```bash
python -m venv venv
source venv/bin/activate          # macOS/Linux
# venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 2. API 키 발급 및 설정 (한국 종목 분석 시 권장)

**DART API 키 (한국 공시/재무제표 — 무료, 30초)**
1. https://opendart.fss.or.kr 접속 → 인증키 신청
2. 이메일로 받은 키를 `.env`에 저장:

```bash
cp .env.example .env
# .env 파일을 열어서 DART_API_KEY=받은키 입력
```

**FRED API 키 (매크로 데이터 — 무료)**
- https://fred.stlouisfed.org/docs/api/api_key.html
- 같은 방식으로 `.env`에 `FRED_API_KEY=` 추가

> API 키 없어도 앱은 실행됩니다. 단 한국 종목 재무 데이터 품질과
> 매크로 사이드바가 제한됩니다.

### 3. 앱 실행
```bash
streamlit run app.py
```
기본 URL: `http://localhost:8501`

## 사용 방법

### Ticker 입력 형식
- **미국**: `NVDA`, `AAPL`, `TSLA`
- **한국 KOSPI**: `005930.KS` (삼성전자), `005380.KS` (현대차)
- **한국 KOSDAQ**: `091990.KQ` (셀트리온헬스케어)

### 한국 종목 Forward EPS 수동 입력 (선택)
한국 종목은 컨센서스 데이터가 yfinance에서 부족합니다.
애널리스트 리포트의 추정치를 직접 입력하면 Forward PEG 계산이 가능합니다.

### Peer 종목 추가
기본 Peer 리스트가 자동 적용되며, 추가로 비교하고 싶은 종목을 직접 입력할 수 있습니다.

## 데이터 출처 (멀티 소스)

| 소스 | 용도 | 비용 | 필요 키 |
|---|---|---|---|
| **yfinance** | 미국 종목 전반 + 한국 기본정보/가격 | 무료 | 없음 |
| **DART OpenAPI** | 한국 종목 재무제표/공시 | 무료 | DART_API_KEY |
| **pykrx** | 한국 외국인/기관/공매도 일별 | 무료 | 없음 |
| **FRED** | 매크로 (금리/환율/유가) | 무료 | FRED_API_KEY |
| SEC EDGAR (Phase 2) | 미국 공시 (8-K, 13F, Form 4) | 무료 | 없음 |
| FMP / FnGuide (Phase 3) | Forward 컨센서스 / 트랜스크립트 | 유료 | - |

### 데이터 라우팅 정책
- **US 종목**: yfinance만
- **KR 종목**: yfinance (가격/시총/기본정보) + **DART (재무제표 우선)** + pykrx (수급)
- 동일 항목은 한국 종목의 경우 DART 값을 우선, 누락 항목만 yfinance 사용

## 개발 로드맵

### Phase 1 (MVP) — 현재
- ✅ CAN SLIM 정량 체크
- ✅ PEG 3변형 + Trap Detection
- ✅ DuPont 분해
- ✅ Earnings Quality / Capital Allocation
- ✅ Calendar / Macro
- ✅ Peer Comparison
- ✅ 섹터 특화 (반도체, 소비재 2개)

### Phase 2 — 확장
- ⏳ DART / SEC EDGAR 공시 트래커
- ⏳ Catalyst Tracker
- ⏳ 외국인/기관/공매도 Flow
- ⏳ Risk Metrics (Beta, IV, Drawdown)
- ⏳ 섹터 모듈 추가 (화장품, SaaS, EV, 금융, 바이오)

### Phase 3 — LLM/유료
- 🔮 Conference Call Transcript 분석
- 🔮 뉴스/공시 자동 요약 → Catalyst
- 🔮 LLM 기반 Investment Memo 자동 생성
- 🔮 FMP / FnGuide 유료 데이터 연동

## 데이터 출처

- **yfinance**: 기본 재무/주가/배당 (무료, 비공식)
- **FRED**: 매크로 (금리, 환율) — API 키 필요 (`config.py`)
- **DART** (Phase 2): 한국 공시
- **SEC EDGAR** (Phase 2): 미국 공시

## 라이선스 / 면책

본 도구는 학습 및 개인 투자 분석 목적이며 투자 권유가 아닙니다.
모든 투자 판단의 책임은 사용자 본인에게 있습니다.
yfinance 데이터는 비공식이므로 중요한 의사결정 전 반드시 원본 공시를 확인하세요.
