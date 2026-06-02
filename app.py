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
<style>
/* === Typography === */
.main, [data-testid="stSidebar"], .stApp {
    font-family: 'IBM Plex Mono', 'JetBrains Mono', 'SF Mono', 'Menlo', 'Monaco', monospace;
}

/* Tighten default spacing */
.block-container {
    padding-top: 2rem;
    padding-bottom: 2rem;
    max-width: 1400px;
}

/* === Headers === */
h1 {
    font-weight: 600 !important;
    letter-spacing: -0.5px;
    margin-bottom: 0.2rem !important;
}
h2, h3 {
    font-weight: 500 !important;
    letter-spacing: 0.3px;
    text-transform: uppercase;
    font-size: 0.85rem !important;
    color: #71717a !important;
    margin-top: 1.5rem !important;
    margin-bottom: 0.8rem !important;
}

/* === Metric labels & values === */
[data-testid="stMetricLabel"] {
    text-transform: uppercase;
    font-size: 0.7rem !important;
    letter-spacing: 0.5px;
    color: #71717a !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.4rem !important;
    font-weight: 500 !important;
    font-family: 'IBM Plex Mono', monospace !important;
}

/* === Tabs === */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 1px solid #27272a;
}
.stTabs [data-baseweb="tab"] {
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-size: 0.8rem;
    padding: 8px 20px;
    color: #71717a;
    border-radius: 0;
    border-bottom: 2px solid transparent;
}
.stTabs [aria-selected="true"] {
    color: #d4d4d8 !important;
    border-bottom: 2px solid #3b82f6 !important;
    background: transparent !important;
}

/* === Dividers === */
hr {
    border-color: #27272a !important;
    margin: 1rem 0 !important;
}

/* === Sidebar === */
[data-testid="stSidebar"] {
    border-right: 1px solid #27272a;
}
[data-testid="stSidebar"] h1 {
    font-size: 1rem !important;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #d4d4d8 !important;
}

/* === Custom signal badges === */
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 0.75rem;
    font-weight: 500;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}
.badge-na { background: #27272a; color: #71717a; }
.badge-positive { background: rgba(22, 163, 74, 0.15); color: #4ade80; }
.badge-negative { background: rgba(220, 38, 38, 0.15); color: #f87171; }
.badge-warning { background: rgba(202, 138, 4, 0.15); color: #fbbf24; }
.badge-neutral { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }

/* === PEG card === */
.peg-card {
    padding: 14px 16px;
    background: #151b23;
    border-left: 3px solid #3b82f6;
    border-radius: 2px;
    margin-bottom: 8px;
}
.peg-card .label {
    font-size: 0.7rem;
    text-transform: uppercase;
    color: #71717a;
    letter-spacing: 0.5px;
}
.peg-card .value {
    font-size: 1.8rem;
    font-weight: 500;
    margin: 2px 0;
}
.peg-card .meta {
    font-size: 0.75rem;
    color: #a1a1aa;
}

/* Suppress some Streamlit defaults */
[data-testid="stHeader"] { background: transparent; }
footer { display: none; }
#MainMenu { visibility: hidden; }
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
        f"## {ticker} &nbsp; <span style='color:#71717a; font-weight: 400; font-size: 1rem;'>{name}</span>",
        unsafe_allow_html=True
    )
    st.markdown(
        f"<span style='color: #71717a; font-size: 0.85rem;'>"
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

    # ---------- Quarterly section ----------
    st.markdown("### Quarterly Performance")
    st.caption("Past quarters + 2 forward quarters (consensus/user input shown in amber).")

    if not quarterly_df.empty:
        _render_timeseries_table(quarterly_df, currency=data["meta"].get("currency", "USD"),
                                 is_annual=False)

        # 차트 2개 (매출 YoY, EPS YoY)
        chart_cols = st.columns(2)
        with chart_cols[0]:
            st.plotly_chart(
                render_yoy_bar_chart(quarterly_df, "revenue_yoy", "Revenue YoY"),
                use_container_width=True,
            )
        with chart_cols[1]:
            st.plotly_chart(
                render_yoy_bar_chart(quarterly_df, "eps_yoy", "EPS YoY"),
                use_container_width=True,
            )
    else:
        st.markdown(badge("N/A", "na") + " &nbsp; No quarterly timeseries data available",
                    unsafe_allow_html=True)

    # ---------- Annual section ----------
    st.markdown("### Annual Performance")
    st.caption("Past years + 2 forward years (consensus/user input shown in amber).")

    if not annual_df.empty:
        _render_timeseries_table(annual_df, currency=data["meta"].get("currency", "USD"),
                                 is_annual=True)

        chart_cols = st.columns(2)
        with chart_cols[0]:
            st.plotly_chart(
                render_yoy_bar_chart(annual_df, "revenue_yoy", "Revenue YoY"),
                use_container_width=True,
            )
        with chart_cols[1]:
            st.plotly_chart(
                render_yoy_bar_chart(annual_df, "eps_yoy", "EPS YoY"),
                use_container_width=True,
            )
    else:
        st.markdown(badge("N/A", "na") + " &nbsp; No annual timeseries data available",
                    unsafe_allow_html=True)

    st.markdown("---")

    # ========== 기존 GROWTH 분석 ==========
    result = analyze_growth(data)
    m = result["metrics"]

    st.markdown("### Snapshot Metrics")
    cols = st.columns(4)
    cols[0].metric("Revenue YoY (Q)", display_value(m["quarterly_revenue_yoy"], format_yoy))
    cols[1].metric("EPS YoY (Q)", display_value(m["quarterly_eps_yoy"], format_yoy))
    cols[2].metric("Revenue 3Y CAGR", display_value(m["revenue_cagr_3y"], format_yoy))
    cols[3].metric("EPS 3Y CAGR", display_value(m["eps_cagr_3y"], format_yoy))

    st.markdown("### Momentum Indicators")

    col1, col2 = st.columns(2)
    with col1:
        accel = m["eps_accelerating"]
        if accel is True:
            st.markdown(badge("ACCELERATING", "positive") + " &nbsp; EPS growth rate increasing QoQ", unsafe_allow_html=True)
        elif accel is False:
            st.markdown(badge("DECELERATING", "warning") + " &nbsp; EPS growth rate slowing QoQ", unsafe_allow_html=True)
        else:
            st.markdown(badge("N/A", "na") + " &nbsp; Insufficient data for momentum check", unsafe_allow_html=True)

    with col2:
        ath = m["net_income_all_time_high"]
        if ath is True:
            st.markdown(badge("ALL-TIME HIGH", "positive") + " &nbsp; TTM net income at record peak", unsafe_allow_html=True)
        elif ath is False:
            st.markdown(badge("BELOW PEAK", "neutral") + " &nbsp; TTM net income not at all-time high", unsafe_allow_html=True)
        else:
            st.markdown(badge("N/A", "na") + " &nbsp; Insufficient historical data", unsafe_allow_html=True)

    # Operating Leverage Decomposition
    st.markdown("### Operating Leverage Decomposition")
    st.caption("Decomposes EPS-revenue growth gap into margin, share count, and non-operating effects.")

    gap = m.get("gap_decomposition", {})
    if gap.get("gap_pct") is not None:
        gap_pct = gap["gap_pct"]
        primary = gap.get("primary_driver", "")
        # Translate
        primary_en = primary.replace("영업레버리지", "Operating Leverage") \
                            .replace("자사주 효과", "Share Buyback") \
                            .replace("비영업 효과", "Non-Operating Items") \
                            .replace("주도", "primary")

        if abs(gap_pct) < 0.05:
            st.markdown(
                badge("ALIGNED", "neutral") +
                f" &nbsp; EPS growth tracks revenue ({gap_pct:+.1%}p delta). Natural operating result.",
                unsafe_allow_html=True
            )
        else:
            sign = "above" if gap_pct > 0 else "below"
            variant = "warning" if abs(gap_pct) > 0.2 else "neutral"
            st.markdown(
                badge(f"GAP {abs(gap_pct):.1%}p", variant) +
                f" &nbsp; EPS growth {sign} revenue growth — {primary_en}",
                unsafe_allow_html=True
            )

            with st.expander("Decomposition breakdown"):
                margin = gap.get("margin_contribution")
                share = gap.get("share_contribution")
                residual = gap.get("residual")
                if margin is not None:
                    st.markdown(f"`Operating Leverage   {margin:+8.1%}p` &nbsp; (margin expansion)")
                if share is not None:
                    st.markdown(f"`Share Buyback       {share:+8.1%}p` &nbsp; (share count change)")
                if residual is not None:
                    st.markdown(f"`Non-Operating       {residual:+8.1%}p` &nbsp; (tax/interest/one-time)")
    else:
        st.markdown(badge("N/A", "na") + " &nbsp; Insufficient data for decomposition", unsafe_allow_html=True)

    # Flags
    if result["flags"]:
        st.markdown("### Flags")
        for f in result["flags"]:
            variant = {"warning": "warning", "good": "positive", "info": "neutral"}.get(f["severity"], "neutral")
            label = {"warning": "RISK", "good": "STRENGTH", "info": "NOTE"}.get(f["severity"], "NOTE")
            render_signal_line(label, _translate_flag_msg(f["msg"]), variant)


# ============================================================
# Tab: Profitability (DuPont)
# ============================================================
def render_profitability_tab(data: dict):
    result = analyze_profitability(data)
    m = result["metrics"]

    # Profile type badge
    type_name = result.get("type", "")
    type_map = {
        "마진 주도형 ★": ("MARGIN-DRIVEN", "positive", "Strong pricing power, brand/moat economics."),
        "효율성 주도형": ("EFFICIENCY-DRIVEN", "neutral", "Capital-light model, high asset turnover."),
        "레버리지 의존형": ("LEVERAGE-DEPENDENT", "warning", "ROE inflated by financial leverage. Examine operating quality."),
        "균형형": ("BALANCED", "neutral", "Three DuPont factors contribute proportionally."),
    }
    if type_name in type_map:
        label, variant, desc = type_map[type_name]
        st.markdown(
            badge(label, variant) + f" &nbsp; <span style='color:#a1a1aa;'>{desc}</span>",
            unsafe_allow_html=True
        )

    st.markdown("### DuPont 3-Factor Decomposition")
    st.caption("ROE = Net Margin × Asset Turnover × Equity Multiplier")

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

    st.markdown("### Margin Structure")
    cols = st.columns(3)
    cols[0].metric("Gross Margin", display_value(m["gross_margin"], format_pct))
    cols[1].metric("Operating Margin", display_value(m["operating_margin"], format_pct))
    cols[2].metric("Net Margin", display_value(m["net_margin"], format_pct))

    # ROE vs COE
    st.markdown("### Value Creation Test")
    above = m.get("roe_above_coe")
    coe = m.get("coe_assumed", 0.10)
    if above is True:
        st.markdown(
            badge("VALUE CREATING", "positive") +
            f" &nbsp; ROE ({format_pct(m['roe'])}) exceeds cost of equity ({format_pct(coe)})",
            unsafe_allow_html=True
        )
    elif above is False:
        st.markdown(
            badge("VALUE DESTROYING", "negative") +
            f" &nbsp; ROE ({format_pct(m['roe'])}) below cost of equity ({format_pct(coe)})",
            unsafe_allow_html=True
        )

    # Flags
    if result["flags"]:
        st.markdown("### Flags")
        for f in result["flags"]:
            variant = {"warning": "warning", "good": "positive", "info": "neutral"}.get(f["severity"], "neutral")
            label = {"warning": "RISK", "good": "STRENGTH", "info": "NOTE"}.get(f["severity"], "NOTE")
            render_signal_line(label, _translate_flag_msg(f["msg"]), variant)


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

    st.markdown("### Valuation Multiples")
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

    # PEG triple
    st.markdown("### PEG — Primary Valuation Signal")
    st.caption("Three variants. Forward 2Y is the most stable (smooths one-off effects).")

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

    # Trap Detection
    st.markdown("### Trap Detection")
    if not result["flags"]:
        st.markdown(badge("CLEAR", "positive") + " &nbsp; No valuation traps detected.", unsafe_allow_html=True)
    else:
        for f in result["flags"]:
            variant = {"warning": "warning", "good": "positive", "info": "neutral"}.get(f["severity"], "neutral")
            label = {"warning": "RISK", "good": "STRENGTH", "info": "NOTE"}.get(f["severity"], "NOTE")
            render_signal_line(label, _translate_flag_msg(f["msg"]), variant)


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

    # HTML 테이블 빌드
    html = ['<table style="width:100%; border-collapse: collapse; font-family: \'IBM Plex Mono\', monospace; font-size: 0.85rem;">']
    html.append('<thead><tr style="border-bottom: 1px solid #27272a;">')
    html.append('<th style="text-align: left; padding: 8px; color: #71717a; font-weight: 500;">Period</th>')
    html.append(f'<th style="text-align: right; padding: 8px; color: #71717a; font-weight: 500;">Revenue ({rev_unit})</th>')
    html.append('<th style="text-align: right; padding: 8px; color: #71717a; font-weight: 500;">Revenue YoY</th>')
    html.append(f'<th style="text-align: right; padding: 8px; color: #71717a; font-weight: 500;">EPS ({eps_unit})</th>')
    html.append('<th style="text-align: right; padding: 8px; color: #71717a; font-weight: 500;">EPS YoY</th>')
    if is_annual:
        html.append('<th style="text-align: right; padding: 8px; color: #71717a; font-weight: 500;">ROE</th>')
    html.append('</tr></thead><tbody>')

    for _, row in df.iterrows():
        is_future = row.get("is_future", False)
        bg_color = "background: rgba(251, 191, 36, 0.08);" if is_future else ""
        period_color = "#fbbf24" if is_future else "#d4d4d8"

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

        # EPS
        eps = row.get("eps")
        if eps is not None and not pd.isna(eps):
            if is_krw:
                eps_str = f"{eps:,.0f}"
            else:
                eps_str = f"{eps:,.2f}"
        else:
            eps_str = "—"

        # EPS YoY
        eps_yoy = row.get("eps_yoy")
        if eps_yoy is not None and not pd.isna(eps_yoy):
            color = "#22c55e" if eps_yoy >= 0 else "#ef4444"
            eps_yoy_str = f'<span style="color:{color}; font-weight: 500;">{eps_yoy*100:+.1f}%</span>'
        else:
            eps_yoy_str = "—"

        # ROE (연간만)
        if is_annual:
            roe = row.get("roe")
            if roe is not None and not pd.isna(roe):
                roe_str = f"{roe*100:.1f}%"
            else:
                roe_str = "—"

        html.append(f'<tr style="{bg_color} border-bottom: 1px solid #1f2937;">')
        html.append(f'<td style="padding: 8px;">{period_html}</td>')
        html.append(f'<td style="padding: 8px; text-align: right;">{rev_str}</td>')
        html.append(f'<td style="padding: 8px; text-align: right;">{rev_yoy_str}</td>')
        html.append(f'<td style="padding: 8px; text-align: right;">{eps_str}</td>')
        html.append(f'<td style="padding: 8px; text-align: right;">{eps_yoy_str}</td>')
        if is_annual:
            html.append(f'<td style="padding: 8px; text-align: right;">{roe_str}</td>')
        html.append('</tr>')

    html.append('</tbody></table>')
    st.markdown("".join(html), unsafe_allow_html=True)


def _render_peg_card(label: str, sublabel: str, peg: dict):
    """Render a single PEG card with verdict color."""
    if peg["value"] is None:
        st.markdown(
            f"""
            <div class="peg-card" style="border-left-color: #52525b;">
                <div class="label">{label}</div>
                <div class="value" style="color: #71717a;">N/A</div>
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
    verdict_color = color_map.get(verdict, "#71717a")

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
    tab_summary, tab_growth, tab_profit, tab_val = st.tabs(
        ["SUMMARY", "GROWTH", "PROFITABILITY", "VALUATION"]
    )

    with tab_summary:
        render_summary_tab(data, user_inputs)
    with tab_growth:
        render_growth_tab(data, user_inputs)
    with tab_profit:
        render_profitability_tab(data)
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
