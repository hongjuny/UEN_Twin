"""Stage-2 review figures for a v1 scenario run (SIMULATED data).

    uv run python scripts/figures_v1.py                    # baseline_weekday -> docs/figures/v1/
    uv run python scripts/figures_v1.py --scenario semester_registration_monday --links usu-logan--wsu-ogden

Runs the scenario once. The 10 s raw values come straight from each simulation tick (on_tick hook); the stored
telemetry is 30 s interval averages (5 min per class), and the 5-min lines are averages of those. Uses Plotly and Playwright
(already project dependencies) to render PNGs.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures" / "v1"
DEFAULT_LINKS = ["uvu-orem--uvu-wasatch", "kane-sd--tdc-stgeorge"]
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
    ap.add_argument("--links", nargs="+", default=DEFAULT_LINKS, help="links for direction plots")
    ap.add_argument("--node", default=SERVER, help="node for the server-session plot")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    from uetn_twin.sim.runner import SimRun
    from uetn_twin.sim.scenario import load_scenario

    raw: dict[str, list] = {lid: [] for lid in args.links}
    sessions: list = []

    def on_tick(sim_s, res):
        for lid in args.links:
            i = res.link_ids.index(lid)
            raw[lid].append((sim_s, res.load_gbps[i, 0].sum(), res.load_gbps[i, 1].sum()))
        sessions.append((sim_s, res.server_sessions[res.node_ids.index(args.node)]))

    run = SimRun(load_scenario(args.scenario), seed=args.seed, on_tick=on_tick)
    out = run.run()
    clock = run.clock
    links = pd.read_parquet(out / "link_telemetry.parquet")
    by_class = pd.read_parquet(out / "link_class_telemetry.parquet")
    nodes = pd.read_parquet(out / "node_telemetry.parquet")
    events = pd.read_parquet(out / "events.parquet")
    for df in (links, by_class, nodes):
        df["t"] = pd.to_datetime(df.t)

    def five_min(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
        return df.set_index("t")[cols].resample("5min", label="right", closed="right").mean().reset_index()

    def mark_overlays(fig: go.Figure) -> None:
        for e in events[events.type == "overlay_start"].itertuples():
            label = __import__("json").loads(e.payload).get("label", "")
            fig.add_vline(x=pd.Timestamp(e.t), line=dict(dash="dot", color="#999"))
            fig.add_annotation(x=pd.Timestamp(e.t), y=1, yref="paper", text=label, showarrow=False, xanchor="left",
                               font=dict(size=11, color="#666"), bgcolor="rgba(255,255,255,0.7)")

    OUT.mkdir(parents=True, exist_ok=True)
    tag = run.scenario.id
    topo_links = {ln.id: ln for ln in run.topo.links}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=2)

        # direction plots: raw 10 s + 5-min average for each requested link
        for lid in args.links:
            ln = topo_links[lid]
            r = pd.DataFrame(raw[lid], columns=["sim_s", "ab", "ba"])
            r["t"] = [clock.at(x) for x in r.sim_s]
            fig = go.Figure()
            for (frm, to), col, color in [((ln.a, ln.b), "ab", "#d62728"), ((ln.b, ln.a), "ba", "#1f77b4")]:
                g = links[(links.link_id == lid) & (links.from_node == frm)]
                fig.add_trace(go.Scatter(x=r.t, y=r[col], mode="lines", line=dict(width=0.7, color=color), opacity=0.45,
                                         name=f"{frm} -> {to}, 10 s raw"))
                m = five_min(g, ["gbps"])
                fig.add_trace(go.Scatter(x=m.t, y=m.gbps, mode="lines", line=dict(width=2.4, color=color),
                                         name=f"{frm} -> {to}, 5-min average"))
            mark_overlays(fig)
            layout(fig, f"{tag}: {lid} ({ln.capacity_gbps:g}G, {ln.confidence}), load by direction", "Gbps (offered load)")
            fig.update_yaxes(rangemode="tozero")
            render(fig, OUT / f"{tag}_{lid}.png", page)

        # exit -> DDC, stacked by class (5-min telemetry)
        e = by_class[(by_class.link_id == EXIT_LINK[0]) & (by_class.from_node == EXIT_LINK[1])]
        wide = e.pivot_table(index="t", columns="class", values="gbps", aggfunc="sum").fillna(0).reset_index()
        fig = go.Figure()
        for c in run.odmap.classes:
            if c in wide:
                fig.add_trace(go.Scatter(x=wide.t, y=wide[c], mode="lines", stackgroup="one", name=c,
                                         line=dict(width=0.5, color=CLASS_COLORS.get(c)), fillcolor=CLASS_COLORS.get(c)))
        mark_overlays(fig)
        layout(fig, f"{tag}: {EXIT_LINK[1]} -> {EXIT_LINK[2]} by traffic class (5-min averages, "
               f"{topo_links[EXIT_LINK[0]].capacity_gbps:g}G link)", "Gbps (offered load)")
        render(fig, OUT / f"{tag}_exit_to_ddc_by_class.png", page)

        # server sessions
        r = pd.DataFrame(sessions, columns=["sim_s", "sessions"])
        r["t"] = [clock.at(x) for x in r.sim_s]
        n = five_min(nodes[nodes.node_id == args.node], ["server_sessions"])
        capacity = run.tc.session_capacity(run.topo)[args.node]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=r.t, y=r.sessions, mode="lines", line=dict(width=0.7, color="#76b7b2"), opacity=0.6,
                                 name="10 s raw"))
        fig.add_trace(go.Scatter(x=n.t, y=n.server_sessions, mode="lines", line=dict(width=2.4, color="#2b6f6a"),
                                 name="5-min average"))
        fig.add_hline(y=capacity, line=dict(dash="dash", color="#888"),
                      annotation_text=f"assumed session capacity {capacity:,}", annotation_position="top left")
        mark_overlays(fig)
        layout(fig, f"{tag}: {args.node} server sessions (registration / login servers, transactional class)",
               "concurrent sessions")
        fig.update_yaxes(rangemode="tozero")
        render(fig, OUT / f"{tag}_{args.node}_server_sessions.png", page)
        browser.close()
    print(f"run: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
