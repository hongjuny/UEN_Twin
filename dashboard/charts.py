"""Time-series charts for the dashboard (Plotly). Pure functions on DataFrames. Everything is SIMULATED.

x axes are wall-clock labels of the simulated day (HH:MM), never calendar dates.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from uetn_twin.palette import CLASS_COLORS

SESSION_COLORS = ("#1f2a44", "#e4572e", "#2b6f6a", "#8c564b")
DIR_COLORS = ("#1f2a44", "#e4572e")
HEIGHT = 250
MARGIN = dict(l=10, r=10, t=30, b=10)


def _x(clock, sim_s) -> list[datetime]:
    return [clock.at(float(s)) for s in sim_s]


def _layout(fig: go.Figure, title: str, yaxis: str, ymax: float | None = None) -> go.Figure:
    fig.update_layout(
        height=HEIGHT, margin=MARGIN, title=dict(text=title, font=dict(size=13), x=0, y=0.97),
        legend=dict(orientation="h", y=-0.18, font=dict(size=10)), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", hovermode="x unified")
    fig.update_xaxes(tickformat="%H:%M", showgrid=False)
    fig.update_yaxes(title=dict(text=yaxis, font=dict(size=11)), rangemode="tozero", range=[0, ymax] if ymax else None,
                     gridcolor="rgba(128,128,128,0.2)")
    return fig


def link_direction_chart(series: pd.DataFrame, clock, capacity_gbps: float, name: str, now_s: float | None = None) -> go.Figure:
    """Load of each direction of one link, with the capacity line. series: link_telemetry rows of one link."""
    fig = go.Figure()
    for k, (direction, g) in enumerate(series.groupby("direction")):
        g = g.sort_values("sim_s")
        fig.add_trace(go.Scatter(x=_x(clock, g.sim_s), y=g.gbps, mode="lines", name=direction.replace("->", " > "),
                                 line=dict(width=2, color=DIR_COLORS[k % 2])))
    if len(series):
        fig.add_hline(y=capacity_gbps, line=dict(dash="dash", color="#d62728", width=1),
                      annotation_text=f"capacity {capacity_gbps:g} G", annotation_position="top left",
                      annotation_font_size=10)
    if now_s is not None:
        fig.add_vline(x=clock.at(now_s), line=dict(color="#888", width=1, dash="dot"))
    peak = float(series.gbps.max()) if len(series) else 0.0
    return _layout(fig, f"{name}: load per direction (Gbps)", "Gbps", max(capacity_gbps, peak) * 1.08 or None)


def class_area_chart(series: pd.DataFrame, clock, name: str) -> go.Figure:
    """What fills the link: stacked Gbps by traffic class, one direction. series: link_class_telemetry rows."""
    fig = go.Figure()
    for cls, g in series.groupby("class"):
        g = g.sort_values("sim_s")
        fig.add_trace(go.Scatter(x=_x(clock, g.sim_s), y=g.gbps, mode="lines", name=cls, stackgroup="one",
                                 line=dict(width=0.5, color=CLASS_COLORS.get(cls, "#666")),
                                 fillcolor=CLASS_COLORS.get(cls, "#666")))
    return _layout(fig, f"{name}: what fills it, by class (Gbps)", "Gbps")


def node_sessions_chart(series: pd.DataFrame | dict[str, pd.DataFrame], clock, name: str = "") -> go.Figure:
    """Server-session load of one node (or several: {label: frame}) as a share of assumed capacity."""
    many = series if isinstance(series, dict) else {name: series}
    fig = go.Figure()
    peak = 0.0
    for k, (label, df) in enumerate(many.items()):
        g = df.sort_values("sim_s")
        fig.add_trace(go.Scatter(x=_x(clock, g.sim_s), y=g.session_utilization * 100, mode="lines", name=label,
                                 line=dict(width=2, color=SESSION_COLORS[k % len(SESSION_COLORS)]), customdata=g.server_sessions,
                                 hovertemplate="%{y:.0f}% (%{customdata:,.0f} sessions)"))
        if len(g):
            peak = max(peak, float(g.session_utilization.max() * 100))
    fig.add_hline(y=100, line=dict(dash="dash", color="#d62728", width=1), annotation_text="capacity",
                  annotation_position="top left", annotation_font_size=10)
    title = " and ".join(many) if len(many) > 1 else name
    return _layout(fig, f"{title}: server sessions (% of assumed capacity)", "% of capacity", max(110.0, peak * 1.08))
