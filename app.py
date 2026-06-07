"""
app.py — Investment Analysis Tool

Professional equity research dashboard.
Style: Bloomberg Terminal / FactSet inspired.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd
import streamlit as st

from modules.data_loader import (
    load_company_data,
    check_data_sources_status,
    clear_cache,
)
from modules.growth_analysis import analyze_growth
from modules.profitability_analysis import analyze_profitability
from modules.valuation_analysis import analyze_valuation
from modules.sector_classifier import get_sector_display_name
from modules.stability_analysis import render_tab as render_stability_tab
from utils.formatting import (
    format_currency, format_pct, format_multiple, format_yoy, format_number,
)


# ============================================================
# Page config
# ============================================================
st.set_page_config(
    page_title="Equity Research Terminal",
    page_icon="◼",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# Custom CSS — Bloomberg Terminal-inspired styling
# ============================================================
st.markdown("""
<!-- Font import: Inter (본문/헤더), IBM Plex Mono (숫자/테이블), Material Symbols (아이콘) -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0" rel="stylesheet">

<style>
/* ============================================================
   COLOR PALETTE — Bloomberg Terminal Style
   ============================================================ */
:root {
    --bg-primary:    #0a0a0a;
    --bg-card:       #141414;
    --bg-elevated:   #1a1a1a;

    --text-primary:    #ffffff;   /* 헤더, 주요 숫자 — 진짜 흰색 */
    --text-secondary:  #d4d4d8;   /* 본문 텍스트 */
    --text-tertiary:   #a1a1aa;   /* 보조 정보, 라벨 */
    --text-muted:      #71717a;   /* 비활성, 단위, 캡션 */

    --border:        #262626;     /* 구분선 (조금 밝게) */
    --border-soft:   #1a1a1a;

    --accent-blue:   #3b82f6;     /* 액센트/링크 */
    --positive:      #22c55e;     /* 양수 */
    --negative:      #ef4444;     /* 음수 */
    --consensus:     #fbbf24;     /* 컨센서스/예상 */
}

/* ============================================================
   TYPOGRAPHY — 하이브리드 (Inter for prose, Plex Mono for data)
   ============================================================ */
.main, [data-testid="stSidebar"], .stApp,
.stMarkdown, p, div, span, label, button {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont,
                 'Helvetica Neue', 'Segoe UI', sans-serif !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* ⭐ Material Icons (Streamlit 위젯의 화살표/아이콘) 예외 처리
   — Inter로 강제되면 아이콘이 '_arrow_right' 같은 텍스트로 보임 */

/* SVG 아이콘들은 폰트 영향 없음 (안전) */

/* Material Symbols/Icons ligature 폰트 강제 보존 */
[data-testid="stIconMaterial"],
[data-testid="stIconMaterial"] *,
.material-icons,
.material-icons-outlined,
.material-symbols-outlined,
[class*="material-symbols"],
span[class*="MaterialIcon"],
span[class*="material-icon"] {
    font-family: 'Material Symbols Outlined', 'Material Symbols Rounded',
                 'Material Icons', 'Material Icons Outlined' !important;
    font-feature-settings: 'liga';
    -webkit-font-feature-settings: 'liga';
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
}

/* Streamlit expander/button 안의 leading icon span 보호 */
[data-testid="stExpander"] summary [data-testid="stIconMaterial"],
button[kind] [data-testid="stIconMaterial"],
[data-testid="stSidebar"] [data-testid="stIconMaterial"] {
    font-family: 'Material Symbols Outlined' !important;
}

/* Inter import에 Material Symbols도 함께 import 추가 */

/* 본문 텍스트 줄간격 + 색상 */
.stMarkdown p {
    color: var(--text-secondary) !important;
    line-height: 1.6 !important;
}

/* === H1 (페이지 제목) === */
h1 {
    font-weight: 700 !important;
    letter-spacing: -0.5px !important;
    color: var(--text-primary) !important;
    font-size: 1.6rem !important;
    margin-bottom: 0.4rem !important;
}

/* === H2/H3 (섹션 제목) === */
h2, h3 {
    font-weight: 600 !important;
    letter-spacing: 0.3px !important;
    text-transform: uppercase;
    font-size: 0.78rem !important;
    color: var(--text-tertiary) !important;
    margin-top: 1.8rem !important;
    margin-bottom: 0.9rem !important;
    border-bottom: 1px solid var(--border) !important;
    padding-bottom: 0.4rem !important;
}

/* === H4 (서브섹션) — 흰색 강조 === */
h4 {
    font-weight: 600 !important;
    color: var(--text-primary) !important;
    font-size: 0.95rem !important;
    margin-top: 1.2rem !important;
}

/* ============================================================
   LAYOUT
   ============================================================ */
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 3rem;
    max-width: 1600px;            /* 1400 → 1600 (양 옆 활용) */
}

/* ============================================================
   SECTION CARDS — 시니어 도구의 핵심 박스 시스템
   ============================================================ */
.section-card {
    background: #141414;
    border: 1px solid #525252;     /* 밝은 회색 — 본인 선택 */
    border-radius: 4px;
    padding: 16px 20px;
    margin-bottom: 16px;
}
.section-card-header {
    font-size: 0.72rem;
    font-weight: 700;
    color: #d4d4d8;
    text-transform: uppercase;
    letter-spacing: 1px;
    border-bottom: 1px solid #404040;
    padding-bottom: 8px;
    margin-bottom: 12px;
}
.section-card-subtitle {
    font-size: 0.78rem;
    color: #a1a1aa;
    margin-top: -8px;
    margin-bottom: 12px;
    line-height: 1.5;
}

/* H2/H3 안에 들어간 헤더는 카드 내부에서 자연스럽게 */
.section-card h3, .section-card h4 {
    border-bottom: none !important;
    padding-bottom: 0 !important;
    margin-top: 0 !important;
    margin-bottom: 8px !important;
}

/* ============================================================
   METRICS — 가장 중요한 위계 변경
   ============================================================ */
[data-testid="stMetricLabel"] {
    text-transform: uppercase;
    font-size: 0.7rem !important;
    letter-spacing: 0.6px !important;
    color: var(--text-muted) !important;
    font-weight: 500 !important;
}
[data-testid="stMetricLabel"] p {
    color: var(--text-muted) !important;
}

[data-testid="stMetricValue"] {
    font-size: 1.5rem !important;
    font-weight: 500 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    color: var(--text-primary) !important;   /* ← 흰색 (위계 ↑) */
    letter-spacing: -0.3px;
}

[data-testid="stMetricDelta"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.8rem !important;
}

/* ============================================================
   TABS
   ============================================================ */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 1px solid var(--border);
}
.stTabs [data-baseweb="tab"] {
    text-transform: uppercase;
    letter-spacing: 0.6px;
    font-size: 0.78rem;
    font-weight: 500;
    padding: 10px 22px;
    color: var(--text-muted);
    border-radius: 0;
    border-bottom: 2px solid transparent;
}
.stTabs [aria-selected="true"] {
    color: var(--text-primary) !important;
    border-bottom: 2px solid var(--accent-blue) !important;
    background: transparent !important;
}

/* ============================================================
   DIVIDERS
   ============================================================ */
hr {
    border-color: var(--border) !important;
    margin: 1.4rem 0 !important;
}

/* ============================================================
   SIDEBAR
   ============================================================ */
[data-testid="stSidebar"] {
    border-right: 1px solid var(--border);
    background-color: var(--bg-card) !important;
}
[data-testid="stSidebar"] h1 {
    font-size: 0.95rem !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--text-primary) !important;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.6rem;
    margin-bottom: 1rem !important;
}
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
    color: var(--text-tertiary) !important;
    font-size: 0.72rem !important;
    border-bottom: none !important;
    padding-bottom: 0 !important;
}
[data-testid="stSidebar"] h5 {
    color: var(--text-primary) !important;
    text-transform: uppercase;
    font-size: 0.7rem !important;
    letter-spacing: 0.5px;
    margin-top: 1rem !important;
    margin-bottom: 0.5rem !important;
}
[data-testid="stSidebar"] label {
    font-size: 0.78rem !important;
    color: var(--text-secondary) !important;
}

/* Sidebar caption */
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
    color: var(--text-muted) !important;
    font-size: 0.72rem !important;
    line-height: 1.5 !important;
}

/* ============================================================
   CAPTIONS
   ============================================================ */
[data-testid="stCaptionContainer"], .stCaption {
    color: var(--text-muted) !important;
    font-size: 0.78rem !important;
    line-height: 1.5 !important;
}

/* ============================================================
   INPUT WIDGETS
   ============================================================ */
.stTextInput input, .stNumberInput input, .stSelectbox > div {
    background-color: var(--bg-elevated) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-primary) !important;
    font-family: 'IBM Plex Mono', monospace !important;
}
.stCheckbox label, .stCheckbox label p {
    color: var(--text-secondary) !important;
    font-size: 0.85rem !important;
}

/* ============================================================
   BADGES
   ============================================================ */
.badge {
    display: inline-block;
    padding: 3px 9px;
    border-radius: 3px;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    font-family: 'Inter', sans-serif;
}
.badge-na { background: var(--border); color: var(--text-muted); }
.badge-positive { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.badge-negative { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.badge-warning { background: rgba(251, 191, 36, 0.15); color: var(--consensus); }
.badge-neutral { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }

/* ============================================================
   PEG CARDS
   ============================================================ */
.peg-card {
    padding: 16px 18px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent-blue);
    border-radius: 4px;
    margin-bottom: 10px;
}
.peg-card .label {
    font-size: 0.7rem;
    text-transform: uppercase;
    color: var(--text-muted);
    letter-spacing: 0.6px;
    font-weight: 600;
}
.peg-card .value {
    font-size: 1.9rem;
    font-weight: 500;
    font-family: 'IBM Plex Mono', monospace;
    color: var(--text-primary);
    margin: 4px 0;
    letter-spacing: -0.5px;
}
.peg-card .meta {
    font-size: 0.78rem;
    color: var(--text-tertiary);
    line-height: 1.5;
}

/* ============================================================
   TABLES (HTML 인라인 테이블 가독성)
   ============================================================ */
table {
    line-height: 1.5 !important;
}

/* ============================================================
   STREAMLIT DEFAULTS — HIDE
   ============================================================ */
[data-testid="stHeader"] { background: transparent; }
footer { display: none; }
#MainMenu { visibility: hidden; }

/* 사이드바 collapse 버튼 보기 좋게 */
[data-testid="collapsedControl"] {
    color: var(--text-tertiary) !important;
}

/* 코드 블록 색상 */
code {
    background: var(--bg-elevated) !important;
    color: var(--positive) !important;
    border: 1px solid var(--border);
    padding: 2px 6px;
    border-radius: 3px;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.85em;
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# Helpers
# ============================================================
def normalize_ticker(raw: str) -> tuple[str, Optional[str]]:
    """
    Auto-normalize ticker. Detects Korean tickers (6-digit numeric) and appends .KS.

    Returns:
        (normalized_ticker, warning_message)
    """
    if not raw:
        return "", None

    ticker = raw.strip().upper()

    # Already has suffix
    if "." in ticker:
        return ticker, None

    # 6-digit numeric → Korean ticker, append .KS
    if re.fullmatch(r"\d{6}", ticker):
        return f"{ticker}.KS", f"Detected Korean ticker. Auto-appended .KS → {ticker}.KS"

    # Otherwise, US ticker
    return ticker, None


def badge(text: str, variant: str = "neutral") -> str:
    """Render an inline badge as HTML."""
    return f'<span class="badge badge-{variant}">{text}</span>'


def section_card_open(title: str, subtitle: str = None) -> str:
    """카드 박스 시작 (HTML 문자열 반환). st.markdown으로 출력."""
    html = '<div class="section-card">'
    if title:
        html += f'<div class="section-card-header">{title}</div>'
    if subtitle:
        html += f'<div class="section-card-subtitle">{subtitle}</div>'
    return html


def section_card_close() -> str:
    """카드 박스 끝."""
    return '</div>'


def render_signal_line(label: str, content: str, variant: str = "neutral"):
    """Render a single signal line: LABEL    ::    content"""
    badge_html = badge(label, variant)
    st.markdown(f"{badge_html} &nbsp; {content}", unsafe_allow_html=True)


def display_value(value, formatter, default: str = "N/A") -> str:
    """Apply formatter if value exists, else 'N/A'."""
    if value is None:
        return default
    try:
        return formatter(value)
    except (TypeError, ValueError):
        return default


# ============================================================
# Sidebar
# ============================================================
def render_sidebar() -> dict:
    with st.sidebar:
        st.markdown("# Equity Research")
        st.caption("Fundamental Analysis Terminal")

        st.markdown("---")

        # Ticker input
        st.markdown("##### Ticker")
        raw_ticker = st.text_input(
            "Ticker",
            value="NVDA",
            label_visibility="collapsed",
            help="US: NVDA, AAPL · KOR: 005930 (auto .KS) or 005930.KS",
        )
        ticker, warning = normalize_ticker(raw_ticker)
        if warning:
            st.caption(f"→ {warning}")

        st.caption("Examples: NVDA · AAPL · 005930.KS · 000660.KS")

        st.markdown("---")

        # Forward EPS manual entry — annual + quarterly
        st.markdown("##### Forward EPS Override")
        st.caption("For equities where consensus is unavailable. Auto-filled from Naver for KR tickers if available.")

        use_manual = st.checkbox("Enable manual override", value=False)

        user_eps_1y = None
        user_eps_2y = None
        user_quarterly_eps = None  # [Q+1, Q+2]
        if use_manual:
            st.markdown("**Annual estimates**")
            v1 = st.number_input(
                "Forward EPS, NTM (1Y)",
                min_value=0.0,
                value=0.0,
                step=0.1,
                format="%.2f",
                help="Next twelve months EPS consensus",
            )
            v2 = st.number_input(
                "Forward EPS, 2Y out",
                min_value=0.0,
                value=0.0,
                step=0.1,
                format="%.2f",
                help="2-year forward EPS estimate. Primary input for main PEG signal.",
            )
            user_eps_1y = v1 if v1 > 0 else None
            user_eps_2y = v2 if v2 > 0 else None

            st.markdown("**Quarterly estimates**")
            st.caption("Next quarter and Q+2 EPS (optional, for finer timeseries chart)")
            q1 = st.number_input(
                "Next Q EPS",
                min_value=0.0,
                value=0.0,
                step=0.01,
                format="%.2f",
            )
            q2 = st.number_input(
                "Q+2 EPS",
                min_value=0.0,
                value=0.0,
                step=0.01,
                format="%.2f",
            )
            user_quarterly_eps = [
                q1 if q1 > 0 else None,
                q2 if q2 > 0 else None,
            ]
            # 둘 다 None이면 그냥 None
            if all(v is None for v in user_quarterly_eps):
                user_quarterly_eps = None

        st.markdown("---")

        # Data sources
        with st.expander("Data Sources", expanded=False):
            status = check_data_sources_status()
            for name, info in status.items():
                mark = "OK" if info["available"] else "X"
                variant = "positive" if info["available"] else "negative"
                st.markdown(
                    f'{badge(mark, variant)} <span style="color: #a1a1aa;">{name}</span>',
                    unsafe_allow_html=True
                )
                if not info["available"]:
                    st.caption(info["message"])

        # Advanced
        with st.expander("Advanced", expanded=False):
            if st.button("Clear cache for this ticker", use_container_width=True):
                if ticker:
                    n = clear_cache(ticker)
                    st.success(f"Cleared {n} cache entry. Reload will refetch.")

        st.markdown("---")

        # Macro placeholder
        st.markdown("##### Macro Context")
        st.caption("Phase 2 — FRED integration pending")
        col1, col2 = st.columns(2)
        col1.metric("USD/KRW", "—")
        col2.metric("US 10Y", "—")
        col1.metric("VIX", "—")
        col2.metric("WTI", "—")

        return {
            "ticker": ticker,
            "user_eps_1y": user_eps_1y,
            "user_eps_2y": user_eps_2y,
            "user_quarterly_eps": user_quarterly_eps,
        }


# ============================================================
# Header — compact, info-dense
# ============================================================
def render_header(data: dict):
    meta = data.get("meta", {})
    info = data.get("info", {})

    ticker = meta.get("ticker", "?")
    name = meta.get("name", ticker)
    currency = meta.get("currency", "USD")
    sector_display = get_sector_display_name(meta.get("sector_internal", "OTHER"))
    country = meta.get("country", "?")

    # Single compact header line
    st.markdown(
        f"## {ticker} &nbsp; <span style='color:#a1a1aa; font-weight: 400; font-size: 1rem;'>{name}</span>",
        unsafe_allow_html=True
    )
    st.markdown(
        f"<span style='color: #a1a1aa; font-size: 0.85rem;'>"
        f"{sector_display} · {country} · {currency} · "
        f"Exchange: {meta.get('exchange', 'N/A')}"
        f"</span>",
        unsafe_allow_html=True
    )

    st.markdown("")

    # Key stats row — 5 columns
    market_cap = meta.get("market_cap")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    trailing_per = info.get("trailingPE")
    dividend_yield = info.get("dividendYield")
    fifty_two_high = info.get("fiftyTwoWeekHigh")

    cols = st.columns(5)
    cols[0].metric(
        "Market Cap",
        display_value(market_cap, lambda v: format_currency(v, currency)),
    )
    cols[1].metric(
        "Price",
        display_value(current_price, lambda v: format_currency(v, currency)),
    )
    cols[2].metric(
        "P/E (TTM)",
        display_value(trailing_per, format_multiple),
    )
    if dividend_yield:
        dy = dividend_yield if dividend_yield < 1 else dividend_yield / 100
        dy_str = format_pct(dy)
    else:
        dy_str = "N/A"
    cols[3].metric("Dividend Yield", dy_str)

    if fifty_two_high and current_price:
        from_high = (current_price / fifty_two_high) - 1
        cols[4].metric(
            "vs 52W High",
            format_pct(from_high, with_sign=True),
        )
    else:
        cols[4].metric("vs 52W High", "N/A")


# ============================================================
# Tab: Summary
# ============================================================
def render_summary_tab(data: dict, user_inputs: dict):
    growth = analyze_growth(data)
    profit = analyze_profitability(data)
    valuation = analyze_valuation(
        data,
        growth_result=growth,
        user_forward_eps_1y=user_inputs.get("user_eps_1y"),
        user_forward_eps_2y=user_inputs.get("user_eps_2y"),
    )

    # === KEY SIGNALS ===
    st.markdown("### Key Signals")

    # Growth
    gm = growth["metrics"]
    qrev = gm.get("quarterly_revenue_yoy")
    qeps = gm.get("quarterly_eps_yoy")
    growth_parts = []
    if qrev is not None:
        growth_parts.append(f"Revenue YoY {format_yoy(qrev)}")
    if qeps is not None:
        growth_parts.append(f"EPS YoY {format_yoy(qeps)}")
    growth_text = " · ".join(growth_parts) if growth_parts else "Data unavailable"
    render_signal_line("GROWTH", growth_text)

    # Profitability
    p_type = profit.get("type", "")
    p_roe = profit["metrics"].get("roe")
    profit_parts = []
    if p_roe is not None:
        profit_parts.append(f"ROE {format_pct(p_roe)}")
    if p_type and p_type != "데이터 부족":
        # Translate Korean types to English
        type_en = {
            "마진 주도형 ★": "Margin-driven (pricing power)",
            "효율성 주도형": "Efficiency-driven (asset turnover)",
            "레버리지 의존형": "Leverage-dependent",
            "균형형": "Balanced",
        }.get(p_type, p_type)
        profit_parts.append(type_en)
    profit_text = " · ".join(profit_parts) if profit_parts else "Data unavailable"
    render_signal_line("PROFITABILITY", profit_text)

    # Valuation
    main_peg = valuation["metrics"]["peg_forward_2y"]
    if main_peg["value"] is not None:
        val_text = f"PEG (Fwd 2Y) {main_peg['value']:.2f} {main_peg['verdict']}"
    else:
        ttm = valuation["metrics"]["peg_ttm"]
        if ttm["value"] is not None:
            val_text = f"PEG (TTM) {ttm['value']:.2f} {ttm['verdict']} · Fwd 2Y unavailable"
        else:
            val_text = "PEG not calculable"
    render_signal_line("VALUATION", val_text)

    # === RISK FLAGS ===
    st.markdown("### Risk Flags & Signals")
    all_flags = growth["flags"] + profit["flags"] + valuation["flags"]

    if not all_flags:
        st.markdown(badge("CLEAR", "positive") + " &nbsp; No notable signals detected.", unsafe_allow_html=True)
    else:
        warning_flags = [f for f in all_flags if f["severity"] == "warning"]
        good_flags = [f for f in all_flags if f["severity"] == "good"]
        info_flags = [f for f in all_flags if f["severity"] == "info"]

        for f in warning_flags:
            render_signal_line("RISK", _translate_flag_msg(f["msg"]), "warning")
        for f in good_flags:
            render_signal_line("STRENGTH", _translate_flag_msg(f["msg"]), "positive")
        for f in info_flags:
            render_signal_line("NOTE", _translate_flag_msg(f["msg"]), "neutral")


# ============================================================
# Tab: Growth
# ============================================================
def render_growth_tab(data: dict, user_inputs: dict):
    from modules.timeseries import extract_timeseries
    from utils.charts import render_yoy_bar_chart

    # ========== TIMESERIES (분기 + 연간, 과거 + 미래) ==========
    ts = extract_timeseries(
        data,
        n_quarters_history=4,
        n_years_history=4,
        user_quarterly_eps=user_inputs.get("user_quarterly_eps"),
        user_annual_eps=[user_inputs.get("user_eps_1y"), user_inputs.get("user_eps_2y")],
        naver_data=data.get("kr_naver_consensus"),
    )
    quarterly_df = ts["quarterly"]
    annual_df = ts["annual"]

    # ========== 상단: Snapshot Metrics + Momentum (2-column 카드) ==========
    result = analyze_growth(data)
    m = result["metrics"]

    top_col1, top_col2 = st.columns([1, 1])

    with top_col1:
        st.markdown(section_card_open("SNAPSHOT METRICS"), unsafe_allow_html=True)
        # 2x2 그리드 (4개 메트릭) - 각 메트릭에 충분한 너비 확보
        row1 = st.columns(2)
        row1[0].metric("Revenue YoY (Q)", display_value(m["quarterly_revenue_yoy"], format_yoy))
        row1[1].metric("EPS YoY (Q)", display_value(m["quarterly_eps_yoy"], format_yoy))
        row2 = st.columns(2)
        row2[0].metric("Revenue 3Y CAGR", display_value(m["revenue_cagr_3y"], format_yoy))
        row2[1].metric("EPS 3Y CAGR", display_value(m["eps_cagr_3y"], format_yoy))
        st.markdown(section_card_close(), unsafe_allow_html=True)

    with top_col2:
        st.markdown(section_card_open("MOMENTUM INDICATORS"), unsafe_allow_html=True)

        # 세로 배치 (카드 너비 좁아도 각 줄 충분한 너비)
        accel = m["eps_accelerating"]
        if accel is True:
            st.markdown(
                badge("ACCELERATING", "positive") +
                ' &nbsp; <span style="color:#d4d4d8;">EPS growth rate increasing QoQ</span>',
                unsafe_allow_html=True
            )
        elif accel is False:
            st.markdown(
                badge("DECELERATING", "warning") +
                ' &nbsp; <span style="color:#d4d4d8;">EPS growth rate slowing QoQ</span>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                badge("N/A", "na") +
                ' &nbsp; <span style="color:#a1a1aa;">Insufficient data for momentum</span>',
                unsafe_allow_html=True
            )

        # 살짝 여백
        st.markdown('<div style="margin-top:8px;"></div>', unsafe_allow_html=True)

        ath = m["net_income_all_time_high"]
        if ath is True:
            st.markdown(
                badge("ALL-TIME HIGH", "positive") +
                ' &nbsp; <span style="color:#d4d4d8;">TTM net income at record peak</span>',
                unsafe_allow_html=True
            )
        elif ath is False:
            st.markdown(
                badge("BELOW PEAK", "neutral") +
                ' &nbsp; <span style="color:#d4d4d8;">TTM net income below all-time high</span>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                badge("N/A", "na") +
                ' &nbsp; <span style="color:#a1a1aa;">Insufficient data for peak check</span>',
                unsafe_allow_html=True
            )

        # Margin trend (있으면)
        m_trend = m.get("margin_trend")
        if m_trend:
            st.markdown(
                f'<div style="margin-top:10px; padding-top:8px; border-top:1px solid #262626;">'
                f'<span style="color:#a1a1aa; font-size:0.78rem;">Margin trend (Y/Y): </span>'
                f'<span style="color:#ffffff; font-family:\'IBM Plex Mono\',monospace; font-size:0.88rem;">'
                f'{m_trend}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
        st.markdown(section_card_close(), unsafe_allow_html=True)

    # ========== Quarterly Performance 카드 ==========
    n_q_future = len(ts.get("quarterly_future_periods", []))
    q_past_count = len(quarterly_df) - n_q_future if not quarterly_df.empty else 0
    q_caption = _build_dynamic_caption(
        past_n=q_past_count, future_n=n_q_future,
        period_unit="quarter", df=quarterly_df,
    )

    st.markdown(section_card_open("QUARTERLY PERFORMANCE", subtitle=q_caption),
                unsafe_allow_html=True)
    if not quarterly_df.empty:
        # 좌우 컬럼: 좌측 테이블, 우측 차트 2개 세로
        q_left, q_right = st.columns([1.3, 1])
        with q_left:
            _render_timeseries_table(quarterly_df, currency=data["meta"].get("currency", "USD"),
                                     is_annual=False)
        with q_right:
            st.plotly_chart(
                render_yoy_bar_chart(quarterly_df, "revenue_yoy", "Revenue YoY", height=200),
                use_container_width=True,
            )
            st.plotly_chart(
                render_yoy_bar_chart(quarterly_df, "eps_yoy", "EPS YoY", height=200),
                use_container_width=True,
            )
    else:
        st.markdown(badge("N/A", "na") + " &nbsp; No quarterly timeseries data available",
                    unsafe_allow_html=True)
    st.markdown(section_card_close(), unsafe_allow_html=True)

    # ========== Annual Performance 카드 ==========
    n_a_future = len(ts.get("annual_future_periods", []))
    a_past_count = len(annual_df) - n_a_future if not annual_df.empty else 0
    a_caption = _build_dynamic_caption(
        past_n=a_past_count, future_n=n_a_future,
        period_unit="year", df=annual_df,
    )

    st.markdown(section_card_open("ANNUAL PERFORMANCE", subtitle=a_caption),
                unsafe_allow_html=True)
    if not annual_df.empty:
        a_left, a_right = st.columns([1.3, 1])
        with a_left:
            _render_timeseries_table(annual_df, currency=data["meta"].get("currency", "USD"),
                                     is_annual=True)
        with a_right:
            st.plotly_chart(
                render_yoy_bar_chart(annual_df, "revenue_yoy", "Revenue YoY", height=200),
                use_container_width=True,
            )
            st.plotly_chart(
                render_yoy_bar_chart(annual_df, "eps_yoy", "EPS YoY", height=200),
                use_container_width=True,
            )
    else:
        st.markdown(badge("N/A", "na") + " &nbsp; No annual timeseries data available",
                    unsafe_allow_html=True)
    st.markdown(section_card_close(), unsafe_allow_html=True)

    # ========== Operating Leverage Decomposition 카드 ==========
    st.markdown(
        section_card_open(
            "OPERATING LEVERAGE DECOMPOSITION",
            subtitle="Decomposes EPS-revenue growth gap into margin, share count, and non-operating effects."
        ),
        unsafe_allow_html=True
    )
    _render_operating_leverage_card(m)
    st.markdown(section_card_close(), unsafe_allow_html=True)

    # ========== Flags 카드 (있으면) ==========
    if result.get("flags"):
        st.markdown(section_card_open("FLAGS"), unsafe_allow_html=True)
        for f in result["flags"]:
            variant = {"warning": "warning", "good": "positive", "info": "neutral"}.get(f["severity"], "neutral")
            label = {"warning": "RISK", "good": "STRENGTH", "info": "NOTE"}.get(f["severity"], "NOTE")
            st.markdown(
                f'{badge(label, variant)} &nbsp; <span style="color:#d4d4d8;">{_translate_flag_msg(f["msg"])}</span>',
                unsafe_allow_html=True
            )
        st.markdown(section_card_close(), unsafe_allow_html=True)


def render_growth_tab_OLD_REMOVED():
    """REMOVED - replaced by new card-based layout"""
    pass


def _render_operating_leverage_card(m: dict):
    """Operating Leverage Decomposition을 카드 안에 렌더링."""
    gap = m.get("gap_decomposition", {})
    if gap.get("gap_pct") is None:
        st.markdown(badge("N/A", "na") + " &nbsp; Insufficient data for decomposition",
                    unsafe_allow_html=True)
        return

    gap_pct = gap["gap_pct"]
    primary = gap.get("primary_driver", "")
    primary_en = primary.replace("영업레버리지", "Operating Leverage") \
                        .replace("자사주 효과", "Share Buyback") \
                        .replace("비영업 효과", "Non-Operating Items") \
                        .replace("주도", "primary")

    if abs(gap_pct) < 0.05:
        st.markdown(
            badge("ALIGNED", "neutral") +
            f" &nbsp; EPS growth tracks revenue ({gap_pct:+.1%}p delta).",
            unsafe_allow_html=True
        )
    else:
        sign = "above" if gap_pct > 0 else "below"
        variant = "warning" if abs(gap_pct) > 0.2 else "neutral"
        st.markdown(
            badge(f"GAP {abs(gap_pct):.1%}p", variant) +
            f" &nbsp; EPS growth {sign} revenue — {primary_en}",
            unsafe_allow_html=True
        )

    # 분해 상세
    margin = gap.get("margin_contribution")
    share = gap.get("share_contribution")
    residual = gap.get("residual")
    st.markdown('<div style="margin-top:10px; font-family:\'IBM Plex Mono\',monospace; font-size:0.82rem;">',
                unsafe_allow_html=True)
    if margin is not None:
        color = "#22c55e" if margin >= 0 else "#ef4444"
        st.markdown(
            f'<div><span style="color:#a1a1aa;">Operating Leverage</span> '
            f'<span style="color:{color}; float:right;">{margin:+.1%}p</span></div>',
            unsafe_allow_html=True
        )
    if share is not None:
        color = "#22c55e" if share >= 0 else "#ef4444"
        st.markdown(
            f'<div><span style="color:#a1a1aa;">Share Buyback</span> '
            f'<span style="color:{color}; float:right;">{share:+.1%}p</span></div>',
            unsafe_allow_html=True
        )
    if residual is not None:
        color = "#22c55e" if residual >= 0 else "#ef4444"
        st.markdown(
            f'<div><span style="color:#a1a1aa;">Non-Operating</span> '
            f'<span style="color:{color}; float:right;">{residual:+.1%}p</span></div>',
            unsafe_allow_html=True
        )
    st.markdown('</div>', unsafe_allow_html=True)


# ============================================================
# Tab: Profitability (DuPont)
# ============================================================
def render_profitability_tab(data: dict):
    result = analyze_profitability(data)
    m = result["metrics"]

    # ========== Profile Type 카드 ==========
    type_name = result.get("type", "")
    type_map = {
        "마진 주도형 ★": ("MARGIN-DRIVEN", "positive", "Strong pricing power, brand/moat economics."),
        "효율성 주도형": ("EFFICIENCY-DRIVEN", "neutral", "Capital-light model, high asset turnover."),
        "레버리지 의존형": ("LEVERAGE-DEPENDENT", "warning", "ROE inflated by financial leverage. Examine operating quality."),
        "균형형": ("BALANCED", "neutral", "Three DuPont factors contribute proportionally."),
    }
    if type_name in type_map:
        label, variant, desc = type_map[type_name]
        st.markdown(section_card_open("PROFILE TYPE"), unsafe_allow_html=True)
        st.markdown(
            badge(label, variant) + f" &nbsp; <span style='color:#d4d4d8;'>{desc}</span>",
            unsafe_allow_html=True
        )
        st.markdown(section_card_close(), unsafe_allow_html=True)

    # ========== DuPont 3-Factor — FULL WIDTH (핵심 메트릭) ==========
    st.markdown(section_card_open(
        "DUPONT 3-FACTOR",
        subtitle="ROE = Net Margin × Asset Turnover × Equity Multiplier"
    ), unsafe_allow_html=True)

    # 4컬럼 전체 너비 (1600px → 각 ~380px, 충분한 너비)
    cols = st.columns(4)
    cols[0].metric("ROE", display_value(m["roe"], format_pct))
    cols[1].metric(
        "Net Margin",
        display_value(m["net_margin"], format_pct),
        help=f"Contribution: {format_pct(m['dupont']['net_margin_contribution']) if m['dupont']['net_margin_contribution'] else 'N/A'}"
    )
    cols[2].metric(
        "Asset Turnover",
        display_value(m["asset_turnover"], format_number),
        help=f"Contribution: {format_pct(m['dupont']['asset_turnover_contribution']) if m['dupont']['asset_turnover_contribution'] else 'N/A'}"
    )
    cols[3].metric(
        "Equity Multiplier",
        display_value(m["leverage"], format_number),
        help=f"Contribution: {format_pct(m['dupont']['leverage_contribution']) if m['dupont']['leverage_contribution'] else 'N/A'}"
    )
    st.markdown(section_card_close(), unsafe_allow_html=True)

    # ========== Margin Structure + Value Creation 좌우 ==========
    mid_col1, mid_col2 = st.columns([1, 1])

    with mid_col1:
        st.markdown(section_card_open("MARGIN STRUCTURE"), unsafe_allow_html=True)
        # 세로 배치 (라벨 + 값 한 줄씩) — 가독성 ↑
        margin_rows = [
            ("Gross Margin", m["gross_margin"]),
            ("Operating Margin", m["operating_margin"]),
            ("Net Margin", m["net_margin"]),
        ]
        margin_html = '<div style="font-family:Inter,sans-serif;">'
        for label, val in margin_rows:
            val_str = format_pct(val) if val is not None else "—"
            margin_html += (
                f'<div style="display:flex; justify-content:space-between; '
                f'align-items:baseline; padding:10px 0; '
                f'border-bottom:1px solid #262626;">'
                f'<span style="color:#a1a1aa; font-size:0.85rem; '
                f'text-transform:uppercase; letter-spacing:0.5px;">{label}</span>'
                f'<span style="color:#ffffff; font-size:1.3rem; font-weight:500; '
                f'font-family:\'IBM Plex Mono\',monospace; letter-spacing:-0.3px;">'
                f'{val_str}</span>'
                f'</div>'
            )
        margin_html += '</div>'
        st.markdown(margin_html, unsafe_allow_html=True)
        st.markdown(section_card_close(), unsafe_allow_html=True)

    with mid_col2:
        # Value Creation Test 별도 카드
        st.markdown(section_card_open(
            "VALUE CREATION TEST",
            subtitle="ROE vs Cost of Equity (assumed 10%)"
        ), unsafe_allow_html=True)

        above = m.get("roe_above_coe")
        coe = m.get("coe_assumed", 0.10)
        roe_val = m.get("roe")

        if above is True and roe_val is not None:
            spread = (roe_val - coe) * 100
            st.markdown(
                f'<div style="text-align:center; padding:8px 0;">'
                f'{badge("VALUE CREATING", "positive")}'
                f'<div style="margin-top:14px; color:#ffffff; font-size:1.8rem; '
                f'font-weight:500; font-family:\'IBM Plex Mono\',monospace;">'
                f'+{spread:.1f}pp</div>'
                f'<div style="color:#a1a1aa; font-size:0.78rem; margin-top:6px;">'
                f'ROE {format_pct(roe_val)} − COE {format_pct(coe)}'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        elif above is False and roe_val is not None:
            spread = (roe_val - coe) * 100
            st.markdown(
                f'<div style="text-align:center; padding:8px 0;">'
                f'{badge("VALUE DESTROYING", "negative")}'
                f'<div style="margin-top:14px; color:#ef4444; font-size:1.8rem; '
                f'font-weight:500; font-family:\'IBM Plex Mono\',monospace;">'
                f'{spread:.1f}pp</div>'
                f'<div style="color:#a1a1aa; font-size:0.78rem; margin-top:6px;">'
                f'ROE {format_pct(roe_val)} − COE {format_pct(coe)}'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                badge("N/A", "na") + ' &nbsp; <span style="color:#a1a1aa;">Insufficient data for ROE/COE comparison</span>',
                unsafe_allow_html=True
            )
        st.markdown(section_card_close(), unsafe_allow_html=True)

    # ========== ROE DuPont Decomposition (시계열) — 큰 카드 ==========
    from modules.dupont_decomposition import calculate_dupont
    dupont_result = calculate_dupont(data, n_history=2)

    st.markdown(section_card_open(
        "ROE DUPONT DECOMPOSITION — TIME SERIES",
        subtitle="Multi-period decomposition: which factor drives ROE change?"
    ), unsafe_allow_html=True)
    if dupont_result is None:
        st.markdown(badge("N/A", "na") + " &nbsp; Insufficient data for DuPont decomposition",
                    unsafe_allow_html=True)
    else:
        _render_dupont_decomposition(dupont_result, data)
    st.markdown(section_card_close(), unsafe_allow_html=True)

    # ========== Flags 카드 ==========
    if result.get("flags"):
        st.markdown(section_card_open("FLAGS"), unsafe_allow_html=True)
        for f in result["flags"]:
            variant = {"warning": "warning", "good": "positive", "info": "neutral"}.get(f["severity"], "neutral")
            label = {"warning": "RISK", "good": "STRENGTH", "info": "NOTE"}.get(f["severity"], "NOTE")
            render_signal_line(label, _translate_flag_msg(f["msg"]), variant)
        st.markdown(section_card_close(), unsafe_allow_html=True)


# ============================================================
# Tab: Valuation (PEG)
# ============================================================
def render_valuation_tab(data: dict, user_inputs: dict):
    growth = analyze_growth(data)
    result = analyze_valuation(
        data,
        growth_result=growth,
        user_forward_eps_1y=user_inputs.get("user_eps_1y"),
        user_forward_eps_2y=user_inputs.get("user_eps_2y"),
    )
    m = result["metrics"]

    # ========== Valuation Multiples 카드 (full-width) ==========
    st.markdown(section_card_open(
        "VALUATION MULTIPLES",
        subtitle="Current snapshot — see time series below for historical context"
    ), unsafe_allow_html=True)
    cols = st.columns(4)
    cols[0].metric("P/E (TTM)", display_value(m["per_ttm"], format_multiple))
    cols[1].metric("Fwd P/E (NTM)", display_value(m["forward_per_1y"], format_multiple))
    cols[2].metric("Fwd P/E (2Y)", display_value(m["forward_per_2y"], format_multiple))
    cols[3].metric("P/B", display_value(m["pbr"], format_multiple))

    cols = st.columns(4)
    cols[0].metric("P/S", display_value(m["psr"], format_multiple))
    cols[1].metric("EV/EBITDA", display_value(m["ev_ebitda"], format_multiple))
    cols[2].metric("ROE (TTM)", display_value(m["roe_ttm"], format_pct))
    cols[3].metric("Cost of Equity", format_pct(m.get("coe_assumed", 0.10)))
    st.markdown(section_card_close(), unsafe_allow_html=True)

    # ========== PEG — Primary Valuation Signal ==========
    st.markdown(section_card_open(
        "PEG — PRIMARY VALUATION SIGNAL",
        subtitle="Three variants. Forward 2Y is the most stable (smooths one-off effects)."
    ), unsafe_allow_html=True)

    pegs = [
        ("PEG (TTM)", "Trailing 2Y EPS CAGR", m["peg_ttm"]),
        ("PEG (Fwd 1Y)", "NTM consensus growth", m["peg_forward_1y"]),
        ("PEG (Fwd 2Y) ★", "2Y forward CAGR — PRIMARY", m["peg_forward_2y"]),
    ]

    cols = st.columns(3)
    for col, (label, sublabel, peg) in zip(cols, pegs):
        with col:
            _render_peg_card(label, sublabel, peg)

    # Inputs used
    inputs = m.get("inputs", {})
    with st.expander("Input transparency"):
        currency = data["meta"].get("currency", "USD")
        st.markdown(f"`Price            {display_value(inputs.get('current_price'), lambda v: format_currency(v, currency))}`")
        st.markdown(f"`EPS (TTM)        {display_value(inputs.get('eps_ttm'), lambda v: format_number(v, 3))}`")
        st.markdown(f"`Fwd EPS (NTM)    {display_value(inputs.get('forward_eps_1y'), lambda v: format_number(v, 3))}  source: {inputs.get('forward_eps_1y_source') or 'N/A'}`")
        st.markdown(f"`Fwd EPS (2Y)     {display_value(inputs.get('forward_eps_2y'), lambda v: format_number(v, 3))}  source: {inputs.get('forward_eps_2y_source') or 'N/A'}`")
    st.markdown(section_card_close(), unsafe_allow_html=True)

    # ========== Phase 3: Valuation Time Series 카드 ==========
    from modules.valuation_timeseries import calculate_valuation_timeseries
    val_ts = calculate_valuation_timeseries(data, n_history=4)

    st.markdown(section_card_open(
        "VALUATION TIME SERIES",
        subtitle="Historical PER/PBR + consensus — automated signal classification"
    ), unsafe_allow_html=True)

    if val_ts is None:
        st.markdown(badge("N/A", "na") + " &nbsp; Insufficient data for valuation time series",
                    unsafe_allow_html=True)
    else:
        _render_valuation_timeseries(val_ts)
    st.markdown(section_card_close(), unsafe_allow_html=True)

    # ========== Trap Detection 카드 ==========
    st.markdown(section_card_open("TRAP DETECTION"), unsafe_allow_html=True)
    if not result["flags"]:
        st.markdown(badge("CLEAR", "positive") + " &nbsp; No valuation traps detected.", unsafe_allow_html=True)
    else:
        for f in result["flags"]:
            variant = {"warning": "warning", "good": "positive", "info": "neutral"}.get(f["severity"], "neutral")
            label = {"warning": "RISK", "good": "STRENGTH", "info": "NOTE"}.get(f["severity"], "NOTE")
            render_signal_line(label, _translate_flag_msg(f["msg"]), variant)
    st.markdown(section_card_close(), unsafe_allow_html=True)


def _render_valuation_timeseries(result: dict):
    """
    Valuation 시계열 렌더링 (PER/PBR/배당수익률).
    듀퐁 분해와 동일한 스타일 (시계열 카드 + 자동 해설 + 임계값 투명).
    """
    components = result["components"]
    avg = result["avg_metrics"]
    country = result["country"]
    source_note = result["source_note"]
    narrative = result["narrative"]
    signals = result["signals"]
    evidence = result["evidence"]
    thresholds = result["thresholds"]
    current = result.get("current")

    # ----- 1) Source note -----
    st.markdown(
        f'<div style="color:#71717a; font-size:0.78rem; margin-bottom:12px;">'
        f'{source_note}</div>',
        unsafe_allow_html=True
    )

    # ----- 2) 시그널 배지 (메인 결론) -----
    if signals:
        primary = signals[0]
        # 큰 배지 + 설명
        st.markdown(
            f'<div style="margin-bottom:14px;">'
            f'<span class="badge badge-{primary["variant"]}" style="font-size:0.85rem; padding:5px 12px;">'
            f'{primary["label"]}'
            f'</span>'
            f' &nbsp; <span style="color:#d4d4d8; font-size:0.92rem;">'
            f'{primary["description"]}'
            f'</span>'
            f'</div>',
            unsafe_allow_html=True
        )

    # ----- 3) PER 시계열 카드들 -----
    if country == "KR" and len(components) >= 2:
        n_periods = len(components)
        per_cols = st.columns(n_periods)

        for i, (_, row) in enumerate(components.iterrows()):
            period = row["period"]
            is_consensus = row.get("is_consensus", False)
            per_val = row.get("per")

            period_color = "#fbbf24" if is_consensus else "#a1a1aa"
            period_label = period + " (E)" if is_consensus else period
            val_color = "#fbbf24" if is_consensus else "#ffffff"
            val_str = f"{per_val:.1f}x" if per_val is not None else "—"

            # 평균 대비 델타 (actual만)
            delta_html = ""
            if not is_consensus and per_val is not None and avg.get("per_avg"):
                delta = (per_val / avg["per_avg"]) - 1
                if abs(delta) >= 0.05:
                    color = "#ef4444" if delta > 0.20 else ("#22c55e" if delta < -0.15 else "#71717a")
                    arrow = "▲" if delta > 0 else "▼"
                    delta_html = (f'<div style="margin-top:5px; color:{color}; '
                                  f'font-size:0.7rem; font-family:\'IBM Plex Mono\',monospace;">'
                                  f'{arrow} {delta*100:+.1f}% vs avg</div>')

            with per_cols[i]:
                st.markdown(
                    f'<div style="text-align:center; padding:14px 8px; '
                    f'background:#0f0f0f; border:1px solid #262626; '
                    f'border-radius:4px;">'
                    f'<div style="color:{period_color}; font-size:0.7rem; '
                    f'margin-bottom:6px; text-transform:uppercase; '
                    f'letter-spacing:0.6px; font-weight:600;">{period_label}</div>'
                    f'<div style="color:{val_color}; font-size:1.5rem; '
                    f'font-weight:600; font-family:\'IBM Plex Mono\',monospace; '
                    f'letter-spacing:-0.5px;">'
                    f'{val_str}</div>'
                    f'{delta_html}'
                    f'</div>',
                    unsafe_allow_html=True
                )

    # ----- 4) 시계열 테이블 (PER / PBR / Dividend Yield) -----
    st.markdown(
        '<div style="margin-top:18px; color:#a1a1aa; font-size:0.82rem;">'
        '<b style="color:#ffffff;">Multi-period Valuation Metrics</b>'
        '</div>',
        unsafe_allow_html=True
    )

    # 테이블 HTML
    html = ['<table style="width:100%; border-collapse:collapse; font-size:0.85rem; margin-top:8px;">']
    html.append('<thead><tr style="border-bottom:1px solid #404040;">')
    html.append('<th style="text-align:left; padding:10px 8px; color:#71717a; '
                'font-weight:600; font-size:0.72rem; text-transform:uppercase; '
                'letter-spacing:0.5px;">Metric</th>')
    for _, row in components.iterrows():
        period = row["period"]
        is_c = row.get("is_consensus", False)
        color = "#fbbf24" if is_c else "#d4d4d8"
        label = period + " (E)" if is_c else period
        html.append(f'<th style="text-align:right; padding:10px 8px; color:{color}; '
                    f'font-weight:600; font-size:0.72rem; text-transform:uppercase; '
                    f'letter-spacing:0.5px;">{label}</th>')

    # 평균 컬럼
    if country == "KR":
        html.append('<th style="text-align:right; padding:10px 8px; color:#3b82f6; '
                    'font-weight:700; font-size:0.72rem; text-transform:uppercase; '
                    'letter-spacing:0.5px;">5Y AVG</th>')
    html.append('</tr></thead><tbody>')

    # 행: PER, PBR, Dividend Yield
    metric_rows = [
        ("PER", "per", "x", avg.get("per_avg")),
        ("PBR", "pbr", "x", avg.get("pbr_avg")),
        ("Dividend Yield", "dividend_yield", "%", avg.get("div_yield_avg")),
    ]

    for metric_label, metric_key, unit, avg_val in metric_rows:
        # 데이터가 하나도 없으면 행 자체를 스킵
        all_vals = [row.get(metric_key) for _, row in components.iterrows()]
        if all(v is None or pd.isna(v) for v in all_vals):
            continue

        html.append('<tr style="border-bottom:1px solid #1f1f1f;">')
        html.append(
            f'<td style="padding:11px 8px;">'
            f'<div style="color:#ffffff; font-weight:600; font-size:0.9rem;">'
            f'{metric_label}</div>'
            f'</td>'
        )

        for _, row in components.iterrows():
            val = row.get(metric_key)
            is_c = row.get("is_consensus", False)

            if val is None or pd.isna(val):
                cell = '<span style="color:#52525b;">—</span>'
            else:
                if unit == "%":
                    val_str = f"{val*100:.2f}%"
                else:
                    val_str = f"{val:.2f}x"
                cell_color = "#fbbf24" if is_c else "#ffffff"
                cell = (f'<div style="color:{cell_color}; font-weight:500; '
                        f'font-family:\'IBM Plex Mono\',monospace; font-size:0.95rem;">'
                        f'{val_str}</div>')

            html.append(f'<td style="padding:11px 8px; text-align:right;">{cell}</td>')

        # 평균 셀
        if country == "KR":
            if avg_val is None:
                avg_str = "—"
            elif unit == "%":
                avg_str = f"{avg_val*100:.2f}%"
            else:
                avg_str = f"{avg_val:.2f}x"
            html.append(
                f'<td style="padding:11px 8px; text-align:right;">'
                f'<div style="color:#60a5fa; font-weight:500; '
                f'font-family:\'IBM Plex Mono\',monospace; font-size:0.95rem;">'
                f'{avg_str}</div>'
                f'</td>'
            )
        html.append('</tr>')

    html.append('</tbody></table>')
    st.markdown("".join(html), unsafe_allow_html=True)

    # ----- 5) 자동 해설 + 근거 박스 -----
    if narrative:
        # 시그널 색상에 맞춰 박스 색상
        variant_colors = {
            "positive": ("#22c55e", "rgba(34,197,94,0.08)"),
            "negative": ("#ef4444", "rgba(239,68,68,0.08)"),
            "warning":  ("#fbbf24", "rgba(251,191,36,0.08)"),
            "neutral":  ("#60a5fa", "rgba(96,165,250,0.08)"),
        }
        primary_variant = signals[0]["variant"] if signals else "neutral"
        color, bg = variant_colors.get(primary_variant, variant_colors["neutral"])

        evidence_html = ""
        if evidence:
            evidence_html = '<div style="margin-top:10px; padding-top:10px; ' \
                            'border-top:1px solid #262626; color:#a1a1aa; ' \
                            'font-size:0.78rem; line-height:1.6;">'
            evidence_html += '<div style="color:#71717a; font-weight:600; ' \
                             'margin-bottom:4px; font-size:0.7rem; letter-spacing:0.5px;">EVIDENCE</div>'
            for e in evidence:
                evidence_html += f'<div style="margin:3px 0;">→ {e}</div>'
            evidence_html += '</div>'

        st.markdown(
            f'<div style="margin-top:18px; padding:14px 16px; '
            f'background:{bg}; border-left:3px solid {color}; '
            f'border-radius:4px; font-size:0.88rem; color:#ffffff; line-height:1.6;">'
            f'<div style="color:{color}; font-size:0.72rem; font-weight:700; '
            f'margin-bottom:6px; letter-spacing:0.6px;">INSIGHT</div>'
            f'{narrative}'
            f'{evidence_html}'
            f'</div>',
            unsafe_allow_html=True
        )

    # ----- 6) 임계값 노출 (투명성) -----
    with st.expander("Signal thresholds (transparency)"):
        threshold_descriptions = {
            "discount_factor": f"DISCOUNT: PER < 5Y avg × {thresholds['discount_factor']} ({(thresholds['discount_factor']-1)*100:.0f}%)",
            "premium_factor": f"PREMIUM: PER > 5Y avg × {thresholds['premium_factor']} (+{(thresholds['premium_factor']-1)*100:.0f}%)",
            "rerating_growth_min": f"RE-RATING: PER < avg × 0.85 + consensus growth > {thresholds['rerating_growth_min']*100:.0f}%",
            "value_trap_revenue_min": f"VALUE TRAP: PER < avg × 0.85 + revenue YoY < {thresholds['value_trap_revenue_min']*100:.0f}%",
            "mean_reversion_band": f"NEAR MEAN: |current - avg| < avg × {thresholds['mean_reversion_band']} (±{thresholds['mean_reversion_band']*100:.0f}%)",
            "cyclical_peak_margin": f"CYCLICAL PEAK: PER near 5Y min + margin > peak × {thresholds['cyclical_peak_margin']}",
        }
        for key, desc in threshold_descriptions.items():
            st.markdown(f'<div style="font-family:\'IBM Plex Mono\',monospace; '
                        f'font-size:0.78rem; color:#a1a1aa; margin:4px 0;">'
                        f'{desc}</div>', unsafe_allow_html=True)


def _build_dynamic_caption(past_n: int, future_n: int, period_unit: str,
                            df: pd.DataFrame) -> str:
    """
    실제 데이터에 맞는 동적 캡션 생성.

    Args:
        past_n: 과거 행 개수
        future_n: 미래 (E/EST) 행 개수
        period_unit: 'quarter' or 'year'
        df: timeseries DataFrame (출처 식별용)

    Returns:
        예시:
        - "Past 4 quarters + 2 forward (Naver consensus, amber)"
        - "Past 4 quarters + 1 forward (user input, amber)"
        - "Past 4 quarters (no forward data available)"
    """
    unit_label = period_unit + ("s" if past_n != 1 else "")

    if future_n == 0:
        return f"Past {past_n} {unit_label} (no forward {period_unit} data available — "\
               f"enable manual override in sidebar to add estimates)"

    # 미래 행의 source 컬럼에서 출처 식별
    source_label = "estimate"
    if df is not None and not df.empty and "source" in df.columns:
        future_sources = df[df.get("is_future", False) == True]["source"].dropna().tolist()
        if future_sources:
            unique_sources = set(future_sources)
            if unique_sources == {"user_input"}:
                source_label = "user input"
            elif unique_sources == {"consensus"}:
                source_label = "Naver consensus"
            elif "user_input" in unique_sources and "consensus" in unique_sources:
                source_label = "Naver consensus + user input"

    forward_label = period_unit + ("s" if future_n != 1 else "")
    return f"Past {past_n} {unit_label} + {future_n} forward {forward_label} "\
           f"({source_label}, shown in amber)"


def _render_dupont_decomposition(result: dict, data: dict):
    """
    ROE 듀퐁 분해 시계열 렌더링.
    본인 책 이미지 스타일 (3-row 분해 + 한 줄 해설).
    """
    components = result["components"]
    country = result["country"]
    source_note = result["source_note"]
    narrative = result["narrative"]

    # ----- 1) 연도별 ROE 헤더 카드 -----
    st.markdown(
        f'<div style="color:#a1a1aa; font-size:0.8rem; margin-bottom:8px;">'
        f'{source_note}</div>',
        unsafe_allow_html=True
    )

    # 연도별 ROE 큰 숫자 카드들
    n_periods = len(components)
    roe_cols = st.columns(n_periods)
    for i, (_, row) in enumerate(components.iterrows()):
        period = row["period"]
        is_consensus = row.get("is_consensus", False)
        roe = row.get("roe_display")

        # 라벨 색상
        period_color = "#fbbf24" if is_consensus else "#a1a1aa"  # actual은 보조색 (라벨이라)
        period_label = period + (" (E)" if is_consensus else "")

        # ROE 값 - actual은 흰색, consensus는 앰버
        roe_str = f"{roe*100:.2f}%" if roe is not None else "—"
        roe_color = "#fbbf24" if is_consensus else "#ffffff"

        # YoY 변화 배지 (이전 행 대비)
        delta_html = ""
        if i > 0 and roe is not None:
            prev_roe = components.iloc[i - 1].get("roe_display")
            if prev_roe is not None:
                delta = (roe - prev_roe) * 100
                if delta >= 0.1:
                    delta_html = (f'<div style="margin-top:6px; color:#22c55e; '
                                  f'font-size:0.78rem; font-family:\'IBM Plex Mono\',monospace;">▲ +{delta:.2f}%p</div>')
                elif delta <= -0.1:
                    delta_html = (f'<div style="margin-top:6px; color:#ef4444; '
                                  f'font-size:0.78rem; font-family:\'IBM Plex Mono\',monospace;">▼ {delta:.2f}%p</div>')
                else:
                    delta_html = ('<div style="margin-top:6px; color:#71717a; '
                                  'font-size:0.78rem;">◯ flat</div>')

        with roe_cols[i]:
            st.markdown(
                f'<div style="text-align:center; padding:16px 10px; '
                f'background:#141414; border:1px solid #262626; '
                f'border-radius:4px;">'
                f'<div style="color:{period_color}; font-size:0.72rem; '
                f'margin-bottom:8px; text-transform:uppercase; letter-spacing:0.6px; '
                f'font-weight:600;">{period_label}</div>'
                f'<div style="color:{roe_color}; font-size:1.8rem; '
                f'font-weight:600; font-family:\'IBM Plex Mono\',monospace; '
                f'letter-spacing:-0.5px;">'
                f'{roe_str}</div>'
                f'{delta_html}'
                f'</div>',
                unsafe_allow_html=True
            )

    # ----- 2) 듀퐁 분해 테이블 (3개 컴포넌트 × N개 기간) -----
    st.markdown(
        f'<div style="margin-top:20px; color:#a1a1aa; font-size:0.82rem; '
        f'font-family:Inter,sans-serif;">'
        f'<b style="color:#ffffff;">ROE</b> = Net Margin × Asset Turnover × Leverage'
        f'</div>',
        unsafe_allow_html=True
    )

    # 테이블 HTML 빌드
    html = ['<table style="width:100%; border-collapse:collapse; '
            'font-family:\'IBM Plex Mono\',monospace; font-size:0.85rem; margin-top:8px;">']

    # 헤더
    html.append('<thead><tr style="border-bottom:1px solid #262626;">')
    html.append('<th style="text-align:left; padding:10px 8px; color:#a1a1aa; '
                'font-weight:500;">Component</th>')
    for _, row in components.iterrows():
        period = row["period"]
        is_c = row.get("is_consensus", False)
        color = "#fbbf24" if is_c else "#d4d4d8"
        label = period + " (E)" if is_c else period
        html.append(f'<th style="text-align:right; padding:10px 8px; '
                    f'color:{color}; font-weight:500;">{label}</th>')
    html.append('</tr></thead><tbody>')

    # 3개 컴포넌트 행
    component_rows = [
        ("Net Margin", "net_margin", "%", "Net Income ÷ Revenue"),
        ("Asset Turnover", "asset_turnover", "x", "Revenue ÷ Avg Assets"),
        ("Leverage", "leverage", "x", "Avg Assets ÷ Avg Equity"),
    ]

    for comp_label, comp_key, unit, formula in component_rows:
        html.append('<tr style="border-bottom:1px solid #262626;">')
        html.append(
            f'<td style="padding:12px 8px;">'
            f'<div style="color:#ffffff; font-weight:600; font-size:0.88rem;">{comp_label}</div>'
            f'<div style="color:#71717a; font-size:0.72rem; margin-top:3px;">'
            f'{formula}</div>'
            f'</td>'
        )

        prev_val = None
        for j, (_, row) in enumerate(components.iterrows()):
            val = row.get(comp_key)
            is_c = row.get("is_consensus", False)

            if val is None or pd.isna(val):
                cell_html = '<span style="color:#71717a;">—</span>'
            else:
                if unit == "%":
                    val_str = f"{val*100:.2f}%"
                else:
                    val_str = f"{val:.2f}x"
                cell_color = "#fbbf24" if is_c else "#ffffff"   # 흰색 강화

                # YoY 델타 (이전 기간 대비)
                delta_html = ""
                if prev_val is not None and not pd.isna(prev_val):
                    delta = val - prev_val
                    if unit == "%":
                        threshold = 0.005  # 0.5%p
                        delta_str = f"{delta*100:+.2f}p.p."
                    else:
                        threshold = 0.02   # 0.02배
                        delta_str = f"{delta:+.2f}x"

                    if abs(delta) >= threshold:
                        d_color = "#22c55e" if delta > 0 else "#ef4444"
                        d_arrow = "▲" if delta > 0 else "▼"
                        delta_html = (f'<div style="margin-top:3px; color:{d_color}; '
                                      f'font-size:0.72rem; font-family:\'IBM Plex Mono\',monospace;">'
                                      f'{d_arrow} {delta_str}</div>')
                    else:
                        delta_html = ('<div style="margin-top:3px; color:#71717a; '
                                      'font-size:0.72rem;">◯ flat</div>')

                cell_html = (f'<div style="color:{cell_color}; font-weight:500; '
                             f'font-family:\'IBM Plex Mono\',monospace; font-size:1rem;">'
                             f'{val_str}</div>{delta_html}')

            html.append(f'<td style="padding:12px 8px; text-align:right;">{cell_html}</td>')
            prev_val = val

        html.append('</tr>')

    html.append('</tbody></table>')
    st.markdown("".join(html), unsafe_allow_html=True)

    # ----- 3) 자동 해설 박스 -----
    if narrative:
        st.markdown(
            f'<div style="margin-top:18px; padding:14px 16px; '
            f'background:rgba(34,197,94,0.08); border-left:3px solid #22c55e; '
            f'border-radius:4px; font-size:0.88rem; color:#ffffff; line-height:1.6;">'
            f'<div style="color:#22c55e; font-size:0.72rem; font-weight:700; '
            f'margin-bottom:6px; letter-spacing:0.6px;">INSIGHT</div>'
            f'{narrative}'
            f'</div>',
            unsafe_allow_html=True
        )

    # ----- 4) 범례 -----
    st.markdown(
        '<div style="margin-top:12px; font-size:0.7rem; color:#71717a; '
        'display:flex; gap:16px;">'
        '<span><span style="color:#22c55e;">▲</span> YoY improvement</span>'
        '<span><span style="color:#ef4444;">▼</span> YoY decline</span>'
        '<span><span style="color:#a1a1aa;">◯</span> flat (small change)</span>'
        '<span><span style="color:#fbbf24;">amber</span> consensus / estimate</span>'
        '</div>',
        unsafe_allow_html=True
    )


def _render_timeseries_table(df: pd.DataFrame, currency: str, is_annual: bool):
    """
    시계열 DataFrame을 HTML 테이블로 렌더링.
    예상 행(is_future=True)은 앰버 배경으로 강조.
    """
    if df is None or df.empty:
        return

    # 통화/단위 라벨
    is_krw = currency == "KRW"
    rev_unit = "억원" if is_krw else "M"
    eps_unit = "원" if is_krw else "$"

    # HTML 테이블 빌드 (Inter for text labels, IBM Plex Mono for numbers)
    html = ['<table style="width:100%; border-collapse: collapse; font-size: 0.85rem;">']
    html.append('<thead><tr style="border-bottom: 1px solid #404040;">')
    html.append('<th style="text-align: left; padding: 10px 8px; color: #71717a; font-weight: 600; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.5px;">Period</th>')
    html.append(f'<th style="text-align: right; padding: 10px 8px; color: #71717a; font-weight: 600; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.5px;">Revenue ({rev_unit})</th>')
    html.append('<th style="text-align: right; padding: 10px 8px; color: #71717a; font-weight: 600; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.5px;">Revenue YoY</th>')
    html.append(f'<th style="text-align: right; padding: 10px 8px; color: #71717a; font-weight: 600; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.5px;">EPS ({eps_unit})</th>')
    html.append('<th style="text-align: right; padding: 10px 8px; color: #71717a; font-weight: 600; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.5px;">EPS YoY</th>')
    if is_annual:
        html.append('<th style="text-align: right; padding: 10px 8px; color: #71717a; font-weight: 600; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.5px;">ROE</th>')
    html.append('</tr></thead><tbody>')

    for _, row in df.iterrows():
        is_future = row.get("is_future", False)
        bg_color = "background: rgba(251, 191, 36, 0.08);" if is_future else ""
        period_color = "#fbbf24" if is_future else "#ffffff"  # 액튜얼은 순백색
        data_color = "#fbbf24" if is_future else "#ffffff"     # 매출/EPS 본 값도 흰색

        # 기간 라벨 (예상이면 '(E)' 추가)
        period_label = row["period"]
        if is_future:
            source = row.get("source", "")
            badge_text = "EST"
            badge_style = "background: rgba(251, 191, 36, 0.2); color: #fbbf24; padding: 1px 5px; border-radius: 3px; font-size: 0.65rem; margin-left: 6px;"
            period_html = f'<span style="color:{period_color};">{period_label}</span><span style="{badge_style}">{badge_text}</span>'
        else:
            period_html = f'<span style="color:{period_color};">{period_label}</span>'

        # 매출
        revenue = row.get("revenue")
        if revenue is not None and not pd.isna(revenue):
            if is_krw:
                rev_str = f"{revenue / 100_000_000:,.0f}"  # 원 → 억
            else:
                rev_str = f"{revenue / 1_000_000:,.0f}"  # → 백만
        else:
            rev_str = "—"

        # 매출 YoY
        rev_yoy = row.get("revenue_yoy")
        if rev_yoy is not None and not pd.isna(rev_yoy):
            color = "#22c55e" if rev_yoy >= 0 else "#ef4444"
            rev_yoy_str = f'<span style="color:{color};">{rev_yoy*100:+.1f}%</span>'
        else:
            rev_yoy_str = "—"

        # EPS (Diluted 메인) + Basic은 tooltip으로
        eps = row.get("eps")
        eps_basic = row.get("eps_basic")
        if eps is not None and not pd.isna(eps):
            if is_krw:
                eps_str_raw = f"{eps:,.0f}"
            else:
                eps_str_raw = f"{eps:,.2f}"

            # Basic EPS 있으면 tooltip 추가 (희석 차이 정보 포함)
            if eps_basic is not None and not pd.isna(eps_basic) and eps != 0:
                if is_krw:
                    basic_str = f"{eps_basic:,.0f}"
                else:
                    basic_str = f"{eps_basic:,.2f}"
                dilution_pct = (eps_basic - eps) / abs(eps) * 100 if eps != 0 else 0
                tooltip = (f"Diluted: {eps_str_raw} | Basic: {basic_str} | "
                           f"Dilution: {dilution_pct:+.1f}%")
                eps_str = (f'<span title="{tooltip}" '
                           f'style="border-bottom: 1px dotted #a1a1aa; cursor: help;">'
                           f'{eps_str_raw}</span>')
            else:
                eps_str = eps_str_raw
        else:
            eps_str = "—"

        # EPS YoY
        eps_yoy = row.get("eps_yoy")
        if eps_yoy is not None and not pd.isna(eps_yoy):
            color = "#22c55e" if eps_yoy >= 0 else "#ef4444"
            eps_yoy_str = f'<span style="color:{color}; font-weight: 500;">{eps_yoy*100:+.1f}%</span>'
        else:
            eps_yoy_str = "—"

        # ROE (연간만) + 출처 표시
        if is_annual:
            roe = row.get("roe")
            roe_source = row.get("roe_source")
            if roe is not None and not pd.isna(roe):
                roe_str = f"{roe*100:.1f}%"
                # 네이버 출처면 작은 표시 추가
                if roe_source == "naver":
                    roe_str = (f'<span title="Source: Naver (Korean equity consensus)" '
                               f'style="border-bottom: 1px dotted #a1a1aa; cursor: help;">'
                               f'{roe_str}</span>'
                               f'<span style="color: #a1a1aa; font-size: 0.7rem; margin-left: 4px;">'
                               f'ⁿ</span>')
            else:
                roe_str = "—"

        html.append(f'<tr style="{bg_color} border-bottom: 1px solid #262626;">')
        html.append(f'<td style="padding: 9px 8px;">{period_html}</td>')
        html.append(f'<td style="padding: 9px 8px; text-align: right; color: {data_color}; font-family: \'IBM Plex Mono\', monospace;">{rev_str}</td>')
        html.append(f'<td style="padding: 9px 8px; text-align: right;">{rev_yoy_str}</td>')
        html.append(f'<td style="padding: 9px 8px; text-align: right; color: {data_color}; font-family: \'IBM Plex Mono\', monospace;">{eps_str}</td>')
        html.append(f'<td style="padding: 9px 8px; text-align: right;">{eps_yoy_str}</td>')
        if is_annual:
            html.append(f'<td style="padding: 9px 8px; text-align: right; color: {data_color}; font-family: \'IBM Plex Mono\', monospace;">{roe_str}</td>')
        html.append('</tr>')

    html.append('</tbody></table>')
    st.markdown("".join(html), unsafe_allow_html=True)


def _render_peg_card(label: str, sublabel: str, peg: dict):
    """Render a single PEG card with verdict color."""
    if peg["value"] is None:
        st.markdown(
            f"""
            <div class="peg-card" style="border-left-color: #71717a;">
                <div class="label">{label}</div>
                <div class="value" style="color: #a1a1aa;">N/A</div>
                <div class="meta">{peg.get('note', '')}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        return

    verdict = peg["verdict"]
    color_map = {
        "✓✓": "#22c55e",
        "✓":  "#4ade80",
        "△":  "#facc15",
        "⚠":  "#fb923c",
        "✗":  "#ef4444",
    }
    verdict_color = color_map.get(verdict, "#a1a1aa")

    growth_used = peg.get("growth_used")
    growth_str = f"Growth: {growth_used:.1%}" if growth_used is not None else ""

    st.markdown(
        f"""
        <div class="peg-card" style="border-left-color: {verdict_color};">
            <div class="label">{label}</div>
            <div class="value">{peg['value']:.2f} <span style="color: {verdict_color}; font-size: 1.2rem;">{verdict}</span></div>
            <div class="meta">{sublabel} · {growth_str}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# Flag message translation (Korean → English where needed)
# ============================================================
def _translate_flag_msg(msg: str) -> str:
    """Translate Korean phrases in flag messages to English."""
    translations = [
        ("분기 매출 역성장", "Quarterly revenue decline"),
        ("분기 EPS 역성장", "Quarterly EPS decline"),
        ("EPS 성장", "EPS growth"),
        ("매출 성장", "revenue growth"),
        ("보다 큼", "exceeds"),
        ("→", "→"),
        ("성장률", "growth rate"),
        ("매우 높은 추정치", "very high estimate"),
        ("달성 가능성 검토 필요", "executability review required"),
        ("향후 2년", "next 2Y"),
        ("향후 1년", "next 1Y"),
        ("EPS 성장이 매출 성장보다", "EPS growth exceeds revenue growth by"),
        ("초과 — 비영업 효과 주도", "— Non-Operating Items primary"),
        ("초과 — 영업레버리지 주도", "— Operating Leverage primary"),
        ("초과 — 자사주 효과 주도", "— Share Buyback primary"),
        ("일회성 효과 가능성", "potential non-recurring effects"),
        ("PEG 분모 변동 위험", "PEG denominator volatility risk"),
        ("PEG 분모 악화 위험", "PEG denominator deterioration risk"),
        ("사이클 산업이고 영업이익률", "Cyclical sector. Operating margin"),
        ("역사적 최고", "historical peak"),
        ("근처", "near"),
        ("사이클 정점 가능성", "cycle peak risk"),
        ("향후 정상화 시", "upon normalization"),
        ("EPS 성장률 가속 (직전 분기 < 당분기)", "EPS growth accelerating (QoQ)"),
        ("EPS 성장률 둔화", "EPS growth decelerating"),
        ("마진 압박 또는 비용 증가", "Margin compression or cost pressure"),
        ("ROE 음수", "ROE negative"),
        ("적자 상태", "Loss-making"),
        ("자기자본비용", "cost of equity"),
        ("가치 파괴 가능성", "potential value destruction"),
        ("재무레버리지", "Equity multiplier"),
        ("안전 기준", "safe threshold"),
        ("초과", "exceeds"),
        ("배 —", "x —"),
        ("ROE가 레버리지에 크게 의존", "ROE heavily reliant on leverage"),
        ("영업 수익성 질적 평가 필요", "Operating quality review required"),
        ("마진 주도형 ROE", "Margin-driven ROE"),
        ("가격 결정력 강함", "strong pricing power"),
        ("EPS 성장의", "Of EPS growth,"),
        ("가 자사주 매입 효과", "attributable to buybacks"),
        ("실질 영업 성장 별도 검토 필요", "Underlying operating growth requires separate review"),
        ("성장 대비 명백히 고평가", "clearly overvalued relative to growth"),
        ("성장률", "growth"),
        ("p", "p"),
    ]
    out = msg
    for ko, en in translations:
        out = out.replace(ko, en)
    return out


# ============================================================
# Main flow
# ============================================================
def main():
    user_inputs = render_sidebar()
    ticker = user_inputs["ticker"]

    if not ticker:
        st.info("Enter a ticker symbol in the sidebar.")
        st.stop()

    # Load data
    with st.spinner(f"Loading {ticker}... (first call may take 1-2 min)"):
        try:
            data = load_company_data(ticker, use_cache=True, verbose=False)
        except ValueError as e:
            st.error(f"Ticker validation failed: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Data load failed: {e}")
            st.info("Try clearing cache from the sidebar or retry shortly.")
            st.stop()

    render_header(data)
    st.markdown("")

    # Tabs
    tab_summary, tab_growth, tab_profit, tab_stab, tab_val = st.tabs(
        ["SUMMARY", "GROWTH", "PROFITABILITY", "STABILITY", "VALUATION"]
    )

    with tab_summary:
        render_summary_tab(data, user_inputs)
    with tab_growth:
        render_growth_tab(data, user_inputs)
    with tab_profit:
        render_profitability_tab(data)
    with tab_stab:
        render_stability_tab(data)
    with tab_val:
        render_valuation_tab(data, user_inputs)

    # Footer
    st.markdown("---")
    fetched = data['meta'].get('fetched_at', 'N/A')
    sources = ', '.join(data.get('data_sources', []))
    st.caption(
        f"Data fetched: {fetched} · Sources: {sources} · "
        f"For research and educational use only. Not investment advice."
    )


if __name__ == "__main__":
    main()
