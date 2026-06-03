"""
utils/charts.py — Plotly 다크 모드 차트

시니어 도구 스타일:
- 다크 배경
- 양수 = 녹색, 음수 = 빨강, 예상 = 앰버(반투명)
- 미니멀 그리드, 라벨 최소화
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go


# 색상 팔레트 (블룸버그 스타일 — 가독성 강화)
COLOR_POSITIVE = "#22c55e"      # 양수 - 진한 녹색
COLOR_NEGATIVE = "#ef4444"      # 음수 - 진한 빨강
COLOR_POSITIVE_FUTURE = "rgba(34, 197, 94, 0.45)"   # 예상 양수 - 반투명 녹색
COLOR_NEGATIVE_FUTURE = "rgba(239, 68, 68, 0.45)"   # 예상 음수 - 반투명 빨강
COLOR_BG = "#0a0a0a"            # 깊은 검정
COLOR_GRID = "#262626"          # 살짝 밝게 (가독성)
COLOR_TEXT = "#a1a1aa"          # 축 라벨
COLOR_TEXT_BRIGHT = "#ffffff"   # 제목/주요


def render_yoy_bar_chart(
    df: pd.DataFrame,
    metric_column: str,
    title: str,
    height: int = 280,
) -> go.Figure:
    """
    YoY 바 차트 (양수/음수 색상 + 예상 구간 반투명).

    Args:
        df: timeseries DataFrame (period, {metric_column}, is_future 필수)
        metric_column: 'revenue_yoy' 또는 'eps_yoy'
        title: 차트 위 표시 제목
        height: 차트 높이 (px)

    Returns:
        plotly Figure
    """
    if df is None or df.empty or metric_column not in df.columns:
        return _empty_figure(title, height)

    # 색상 결정
    colors = []
    for _, row in df.iterrows():
        val = row.get(metric_column)
        is_future = row.get("is_future", False)
        if val is None or pd.isna(val):
            colors.append("rgba(100, 100, 100, 0.3)")
            continue
        if is_future:
            colors.append(COLOR_POSITIVE_FUTURE if val >= 0 else COLOR_NEGATIVE_FUTURE)
        else:
            colors.append(COLOR_POSITIVE if val >= 0 else COLOR_NEGATIVE)

    # 텍스트 라벨 (값을 막대 위에 표시)
    text_labels = []
    for val in df[metric_column]:
        if val is None or pd.isna(val):
            text_labels.append("")
        else:
            text_labels.append(f"{val*100:+.1f}%")

    fig = go.Figure(
        data=[
            go.Bar(
                x=df["period"],
                y=[v * 100 if (v is not None and not pd.isna(v)) else 0 for v in df[metric_column]],
                marker_color=colors,
                text=text_labels,
                textposition="outside",
                textfont=dict(size=10, color=COLOR_TEXT),
                hovertemplate="%{x}<br>%{text}<extra></extra>",
            )
        ]
    )

    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=13, color=COLOR_TEXT_BRIGHT, family="Inter, sans-serif"),
            x=0,
            y=0.95,
            xanchor="left",
        ),
        height=height,
        margin=dict(l=40, r=20, t=40, b=40),
        paper_bgcolor=COLOR_BG,
        plot_bgcolor=COLOR_BG,
        font=dict(family="Inter, sans-serif", color=COLOR_TEXT, size=10),
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            color=COLOR_TEXT,
            tickfont=dict(size=10, family="IBM Plex Mono, monospace"),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=COLOR_GRID,
            zeroline=True,
            zerolinecolor=COLOR_TEXT,
            zerolinewidth=1,
            color=COLOR_TEXT,
            tickfont=dict(size=9, family="IBM Plex Mono, monospace"),
            ticksuffix="%",
        ),
        showlegend=False,
        bargap=0.35,
    )

    return fig


def _empty_figure(title: str, height: int) -> go.Figure:
    """데이터 없을 때 표시할 빈 차트."""
    fig = go.Figure()
    fig.add_annotation(
        text="No data available",
        showarrow=False,
        font=dict(size=12, color=COLOR_TEXT),
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color=COLOR_TEXT)),
        height=height,
        margin=dict(l=40, r=20, t=40, b=40),
        paper_bgcolor=COLOR_BG,
        plot_bgcolor=COLOR_BG,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig
