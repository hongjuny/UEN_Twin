"""Stage-2 review figures for a v1 scenario run (SIMULATED data).

    uv run python scripts/figures_v1.py                    # baseline_weekday -> docs/figures/v1/
    uv run python scripts/figures_v1.py --scenario semester_registration_monday

Runs the scenario once. The 10 s raw values come straight from each simulation tick (on_tick hook); the stored
telemetry is 30 s interval averages, and the 5-min lines are averages of those. Uses Plotly and Playwright
(already project dependencies) to render PNGs.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures" / "v1"
GATEWAY = ("uvu-orem--uvu-wasatch", "uvu-orem", "uvu-wasatch")
EXIT_LINK = ("slc-level3--slc-ddc", "slc-level3", "slc-ddc")
SERVER = "uvu-orem"
CLASS_COLORS = {"k12_instruction": "#4e79a7", "general_internet": "#59a14f", "streaming": "#e15759",
                "telehealth": "#b07aa1", "research_bulk": "#f28e2b", "transactional": "#76b7b2"}


def render(fig: go.Figure, dest: Path, page) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(fig.to_html(include_plotlyjs=True, full_html=True, config={"displayModeBar": False}))
        html = f.name
    page.goto(Path(html).as_uri())
    page.wait_for_selector(".main-svg")
    page.locator(".js-plotly-plot").screenshot(path=str(dest))
    Path(html).unlink()
    print("wrote", dest.relative_to(ROOT))


def layout(fig: go.Figure, title: str, ytitle: str) -> go.Figure:
    fig.update_layout(title=dict(text=f"<b>SIMULATED</b>  {title}", x=0.01), width=1400, height=520,
                      template="plotly_white", margin=dict(l=70, r=20, t=60, b=50), yaxis_title=ytitle,
                      legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"),
                      xaxis=dict(title="simulated time of day", tickformat="%H:%M", dtick=2 * 3600 * 1000))
    return fig


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="baseline_weekday")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    from uetn_twin.sim.runner import SimRun
    from uetn_twin.sim.scenario import load_scenario

    raw = []

    def on_tick(sim_s, res):
        i = res.link_ids.index(GATEWAY[0])
        k = res.node_ids.index(SERVER)
        raw.append((sim_s, res.load_gbps[i, 0].sum(), res.load_gbps[i, 1].sum(), res.server_sessions[k]))

    run = SimRun(load_scenario(args.scenario), seed=args.seed, on_tick=on_tick)
    out = run.run()
    clock = run.clock
    r = pd.DataFrame(raw, columns=["sim_s", "fwd", "rev", "sessions"])
    r["t"] = [clock.at(s) for s in r.sim_s]
    conn = sqlite3.connect(out / "telemetry.sqlite")
    links = pd.read_sql("SELECT * FROM link_telemetry WHERE link_id IN (?, ?)", conn, params=(GATEWAY[0], EXIT_LINK[0]))
    nodes = pd.read_sql("SELECT * FROM node_telemetry WHERE node_id = ?", conn, params=(SERVER,))
    conn.close()
    for df in (links, nodes):
        df["t"] = pd.to_datetime(df.t)

    def five_min(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
        return df.set_index("t")[cols].resample("5min", label="right", closed="right").mean().reset_index()

    OUT.mkdir(parents=True, exist_ok=True)
    tag = run.scenario.id
    cap = {ln.id: ln.capacity_gbps for ln in run.topo.links}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=2)

        # 1. gateway, both directions: raw 10 s + 5-min average
        fig = go.Figure()
        for (frm, to), col, color in [((GATEWAY[1], GATEWAY[2]), "fwd", "#d62728"), ((GATEWAY[2], GATEWAY[1]), "rev", "#1f77b4")]:
            g = links[(links.link_id == GATEWAY[0]) & (links.from_node == frm)]
            fig.add_trace(go.Scatter(x=r.t, y=r[col], mode="lines", line=dict(width=0.6, color=color), opacity=0.35,
                                     name=f"{frm} -> {to}, 10 s raw"))
            m = five_min(g, ["gbps"])
            fig.add_trace(go.Scatter(x=m.t, y=m.gbps, mode="lines", line=dict(width=2.4, color=color),
                                     name=f"{frm} -> {to}, 5-min average"))
        layout(fig, f"{tag}: eastern gateway {GATEWAY[0]} ({cap[GATEWAY[0]]:g}G, class inferred), load by direction",
               "Gbps (offered load)")
        render(fig, OUT / f"{tag}_gateway_directions.png", page)

        # 2. exit -> DDC, stacked by class (5-min averages)
        e = links[(links.link_id == EXIT_LINK[0]) & (links.from_node == EXIT_LINK[1])]
        cols = [f"gbps_{c}" for c in run.odmap.classes]
        m = five_min(e, cols)
        fig = go.Figure()
        for c in run.odmap.classes:
            fig.add_trace(go.Scatter(x=m.t, y=m[f"gbps_{c}"], mode="lines", stackgroup="one", name=c,
                                     line=dict(width=0.5, color=CLASS_COLORS.get(c)), fillcolor=CLASS_COLORS.get(c)))
        layout(fig, f"{tag}: {EXIT_LINK[1]} -> {EXIT_LINK[2]} by traffic class (5-min averages, {cap[EXIT_LINK[0]]:g}G link)",
               "Gbps (offered load)")
        render(fig, OUT / f"{tag}_exit_to_ddc_by_class.png", page)

        # 3. UVU server sessions
        n = five_min(nodes, ["server_sessions"])
        capacity = run.tc.session_capacity(run.topo)[SERVER]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=r.t, y=r.sessions, mode="lines", line=dict(width=0.6, color="#76b7b2"), opacity=0.5,
                                 name="10 s raw"))
        fig.add_trace(go.Scatter(x=n.t, y=n.server_sessions, mode="lines", line=dict(width=2.4, color="#2b6f6a"),
                                 name="5-min average"))
        fig.add_hline(y=capacity, line=dict(dash="dash", color="#888"),
                      annotation_text=f"assumed session capacity {capacity:,}", annotation_position="top left")
        layout(fig, f"{tag}: UVU server sessions (registration / login servers, transactional class)",
               "concurrent sessions")
        fig.update_yaxes(rangemode="tozero")
        render(fig, OUT / f"{tag}_uvu_server_sessions.png", page)
        browser.close()
    print(f"run: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
