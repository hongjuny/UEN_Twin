"""Streamlit entry point: ``uv run streamlit run dashboard/app.py``. Everything shown is SIMULATED.

Modes: Replay (browse a saved run with the time slider) and Live (follow a run started with ``uetn-twin live``).
Optional URL parameters (used for reproducible screenshots): ``?mode=live``, ``?run=<scenario id>``, ``?t=HH:MM``,
``?node=<node id>``, ``?link=<link id>``.
Set UETN_OUT_DIR to read runs from a directory other than ``outputs/`` (or set UETN_TWIN_OUTPUTS for both).
"""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402
from charts import class_area_chart, link_direction_chart, node_sessions_chart  # noqa: E402
from data import (  # noqa: E402
    RunData, default_time, kpi_values, link_state, list_runs, node_session_util, overlay_infos, session_nodes, snap, top_links_frame,
    window,
)
from map_view import build_map  # noqa: E402
from panels import kpi_tiles, node_detail, scenario_panel, top_links_table  # noqa: E402

from uetn_twin import topology  # noqa: E402
from uetn_twin.engine import DEFAULT_OUT  # noqa: E402

OUT_DIR = Path(os.environ.get("UETN_OUT_DIR", DEFAULT_OUT))
LIVE_REFRESH_S = 2.5
PLAY_MIN = 10  # simulated minutes per play step in Replay
MAX_SLIDER_OPTIONS = 1500

st.set_page_config(page_title="UETN Twin (simulated)", layout="wide")
st.markdown(
    "<style>.block-container{padding-top:2.2rem;padding-bottom:0.5rem}"
    ".sim-badge{position:fixed;top:0.6rem;right:7rem;z-index:999999;background:#d62728;color:#fff;font-weight:700;"
    "letter-spacing:0.08em;padding:0.2rem 0.7rem;border-radius:4px;font-size:0.85rem}</style>"
    "<div class='sim-badge'>SIMULATED</div>", unsafe_allow_html=True)


@st.cache_data
def load_topology():
    return topology.load()


topo = load_topology()
nodes = topo.node_map()
site_counts = {g.parent: g.k12_sites + g.higher_ed_sites + g.healthcare_sites for g in topo.sites}
runs = list_runs(OUT_DIR)

st.markdown("#### UETN backbone digital twin")
st.caption("Simulated traffic on a flow-level model. Sites, demand and latencies are assumptions; "
           "see docs/DATA_PROVENANCE.md.")

if not runs:
    st.warning("No simulation runs found. Run `uv run uetn-twin run baseline_weekday` first "
               "(or `uv run uetn-twin live <scenario>` and choose Live).")
    st.stop()

qp = st.query_params
with st.sidebar:
    mode = st.radio("Mode", ["Replay", "Live"], index=1 if qp.get("mode") == "live" else 0, horizontal=True,
                    help="Replay: browse a saved run. Live: follow a run started with `uetn-twin live`")
    shown = sorted(runs, key=lambda r: r["status"] != "running") if mode == "Live" else runs  # live: running runs first
    want = qp.get("run")
    index = next((i for i, r in enumerate(shown) if want in (r["name"], r["scenario"])), 0)
    run_info = st.selectbox("Run", shown, index=index, key=f"run_{mode}_{st.session_state.get('run_gen', 0)}",
                            format_func=lambda r: f"{r['scenario']} ({r['status']}) {r['name'][-15:-9]}")
    tier_mode = st.radio("Nodes", ["core", "core+distribution"], index=1)
    show_labels = st.checkbox("Show labels", value=True)
    all_classes = sorted({ln.link_class.value for ln in topo.links})
    classes = set(st.multiselect("Link classes", all_classes, default=all_classes))
    emphasize = st.checkbox("Emphasize inferred links (assumed links are always faded)", value=False)
    node_opts = ["-"] + sorted(nodes)
    inspect = st.selectbox("Inspect node", node_opts, index=node_opts.index(qp["node"]) if qp.get("node") in nodes else 0,
                           format_func=lambda i: i if i == "-" else f"{nodes[i].name} ({i})",
                           help="Clicking a node on the map also works when nothing is chosen here")
    link_opts = ["busiest now"] + [ln.id for ln in topo.links]
    link_pick = st.selectbox("Inspect link (charts)", link_opts,
                             index=link_opts.index(qp["link"]) if qp.get("link") in link_opts else 0)

run_path = OUT_DIR / run_info["name"]
live = mode == "Live" and run_info["status"] == "running"


def watch_for_new_run() -> None:
    """Live mode while the shown run is not running: switch to a run that has just been started."""
    if any(r["status"] == "running" for r in list_runs(OUT_DIR)):
        st.session_state["run_gen"] = st.session_state.get("run_gen", 0) + 1  # new widget id: the sidebar redraws
        st.rerun(scope="app")


if mode == "Live" and not live:
    st.fragment(watch_for_new_run, run_every=LIVE_REFRESH_S)()


def initial_time(run: RunData, options: list[float]) -> float:
    q = st.query_params.get("t")
    if q:
        try:
            return snap(options, run.clock.seconds_until(q))
        except ValueError:
            pass
    return default_time(run, options)


def view() -> None:
    run = RunData(run_path)
    times = run.times()
    if not times:
        st.info("Waiting for the first telemetry interval ...")
        return
    if live and run.status != "running":  # the run ended while following it: redraw the page once without auto-refresh
        key = f"finished_{run_path.name}"
        if not st.session_state.get(key):
            st.session_state[key] = True
            st.rerun(scope="app")

    play = False
    if mode == "Live":
        now_s = times[-1]
        badge = {"running": "\U0001f534 LIVE (simulated)", "stalled": "⚠ run stalled"}.get(run.status, "run finished")
        speed = f", {run.meta['speed']:g}x speed" if run.meta.get("speed") else ""
        st.progress(min(now_s / run.duration_s, 1.0), text=f"{badge}: {run.label(now_s)} "
                    f"({now_s / run.duration_s:.0%} of {run.scenario.duration_hours:g} simulated hours{speed})")
    else:
        stride = max(1, math.ceil(len(times) / MAX_SLIDER_OPTIONS))
        options = times[::stride]
        if options[-1] != times[-1]:
            options.append(times[-1])
        tkey = f"t_{run_path.name}"
        if st.session_state.get(tkey) not in options:
            st.session_state[tkey] = initial_time(run, options)
        if st.session_state.pop("advance", False):  # set by the play loop below, applied before the slider exists
            nxt = snap(options, st.session_state[tkey] + PLAY_MIN * 60)
            st.session_state[tkey] = nxt if nxt > st.session_state[tkey] else options[0]
        c_time, c_play = st.columns([8, 1])
        now_s = c_time.select_slider("Time", options=options, key=tkey, format_func=run.label)
        play = c_play.toggle("Play", key="play")
        if run.status == "stalled":
            st.warning("This run is marked as running but nothing was written recently; showing what was recorded.")

    snapshot = run.at(now_s)
    links, node_rows = snapshot["links"], snapshot["nodes"].set_index("node_id")
    state = link_state(links, run.down_links(now_s))
    sessions = node_session_util(snapshot["nodes"])
    node_demand = node_rows.demand_gbps.to_dict()
    overlays = overlay_infos(run, now_s)

    left, right = st.columns([4, 4])
    selected = None if inspect == "-" else inspect
    with left:
        fig = build_map(topo, state, node_demand, site_counts, tier_mode, classes, emphasize,
                        selected or st.session_state.get("clicked"), show_labels, node_sessions=sessions)
        event = st.plotly_chart(fig, width="content", on_select="rerun", selection_mode="points", key="map",
                               config={"topojsonURL": "/app/static/un/"})  # map outline served locally, no internet needed
        clicked = next((p["customdata"] for p in event.selection.points if p.get("customdata") in nodes), None) if event else None
        st.session_state["clicked"] = clicked
    with right:
        scenario_panel(run, now_s, overlays)
        st.caption(f"{run.label(now_s)} (simulated)  |  utilization is offered load; the map shows the busier direction")
        kpi_tiles(kpi_values(links, snapshot["nodes"], snapshot["totals"], site_counts),
                  show_unreachable=bool(run.scenario.events))
        top_links_table(top_links_frame(links, topo))
        node_id = selected or clicked
        if node_id:
            st.divider()
            node_detail(topo, node_id, state, node_rows.loc[node_id] if node_id in node_rows.index else None)

    # ---- time series (rolling 2 simulated hours ending now) ----
    since, until = window(now_s)
    link_id = max(state, key=lambda x: state[x]["utilization"]) if link_pick == "busiest now" else link_pick
    ln = next(x for x in topo.links if x.id == link_id)
    link_name = f"{nodes[ln.a].name} - {nodes[ln.b].name}"
    busier = max(state[link_id]["dirs"], key=lambda d: d["utilization"])
    overlay_nodes = session_nodes(run)
    sess_nodes = [node_id] if node_id else (overlay_nodes or ([max(sessions, key=sessions.get)] if sessions else []))
    c1, c2, c3 = st.columns(3)
    c1.plotly_chart(link_direction_chart(run.link_series(link_id, since, until), run.clock, ln.capacity_gbps, link_name, now_s),
                    width="stretch", key="chart_link")
    c2.plotly_chart(class_area_chart(run.class_series(link_id, busier["frm"], since, until), run.clock,
                                     f"{nodes[busier['frm']].name} > {nodes[busier['to']].name}"), width="stretch", key="chart_class")
    if sess_nodes:
        c3.plotly_chart(node_sessions_chart({nodes[n].name: run.node_series(n, since, until) for n in sess_nodes}, run.clock),
                        width="stretch", key="chart_sessions")
    st.caption("Per-class values are recorded every 5 minutes, link totals every 30 seconds. "
               "Latency in hover text is a rough indicative queueing estimate.")

    if play:
        time.sleep(0.4)
        st.session_state["advance"] = True
        st.rerun(scope="app")


if live:
    st.fragment(view, run_every=LIVE_REFRESH_S)()
else:
    view()
