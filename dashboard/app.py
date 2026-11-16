"""Streamlit entry point: ``uv run streamlit run dashboard/app.py``.

Optional URL parameter ``?t=HH:MM`` sets the initial time (used for reproducible screenshots).
Set UETN_OUT_DIR to read runs from a directory other than ``outputs/``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from map_view import build_map  # noqa: E402
from panels import kpi_tiles, kpi_values, node_detail, top_links_frame, top_links_table  # noqa: E402

from uetn_twin import topology  # noqa: E402
from uetn_twin.engine import DEFAULT_OUT  # noqa: E402
from uetn_twin.traffic import hourly_factor, node_peak_demand  # noqa: E402

OUT_DIR = Path(os.environ.get("UETN_OUT_DIR", DEFAULT_OUT))
DAY_LABEL = {"weekday_semester": "weekday (semester)", "weekend": "weekend", "break": "school break"}  # synthetic day, no real date
PLAY_STEP = 6  # steps per tick while playing (6 x 5 min = 30 min)

st.set_page_config(page_title="UETN Twin", layout="wide")
st.markdown("<style>.block-container{padding-top:2.2rem;padding-bottom:0.5rem}</style>", unsafe_allow_html=True)


@st.cache_data
def load_topology():
    return topology.load()


@st.cache_data
def list_runs(out_dir: str) -> list[tuple[str, str]]:
    """(run name, profile) for every run, newest first."""
    runs = []
    for p in sorted(Path(out_dir).glob("run_*"), reverse=True):
        if (p / "snapshots.parquet").exists() and (p / "meta.json").exists():
            runs.append((p.name, json.loads((p / "meta.json").read_text())["profile"]))
    return runs


@st.cache_data
def load_run(out_dir: str, name: str) -> tuple[pd.DataFrame, dict]:
    p = Path(out_dir) / name
    return pd.read_parquet(p / "snapshots.parquet"), json.loads((p / "meta.json").read_text())


topo = load_topology()
runs = list_runs(str(OUT_DIR))

st.markdown("#### UETN backbone digital twin")
st.caption("v0 flow-level model. Most data is estimated (map / inferred / assumed); see docs/DATA_PROVENANCE.md.")

if not runs:
    st.warning("No simulation runs found. Run `uv run uetn-twin simulate --hours 24` first.")
    st.stop()

nodes = topo.node_map()
with st.sidebar:
    profiles = sorted({p for _, p in runs})
    profile = st.selectbox("Traffic profile", profiles, help="Only profiles with a precomputed run are listed")
    run_name = st.selectbox("Run", [n for n, p in runs if p == profile])
    tier_mode = st.radio("Nodes", ["core", "core+distribution"], index=1)  # external returns in v1
    show_labels = st.checkbox("Show labels", value=True)
    all_classes = sorted({ln.link_class.value for ln in topo.links})
    classes = set(st.multiselect("Link classes", all_classes, default=all_classes))
    emphasize = st.checkbox("Emphasize inferred links (assumed links are always faded)", value=False)
    inspect = st.selectbox("Inspect node", ["-"] + sorted(nodes), format_func=lambda i: i if i == "-" else f"{nodes[i].name} ({i})",
                           help="Clicking a node on the map also works when nothing is chosen here")

df, meta = load_run(str(OUT_DIR), run_name)
times = [pd.Timestamp(x) for x in sorted(df.t.unique())]
tkey = f"t_{run_name}"
if tkey not in st.session_state:
    default = times[0]
    q = st.query_params.get("t")
    if q:
        try:
            hh, mm = q.split(":")
            cand = times[0].normalize() + pd.Timedelta(hours=int(hh), minutes=int(mm))
            default = cand if cand in times else default
        except ValueError:
            pass
    else:
        cand = times[0].normalize() + pd.Timedelta(hours=10)
        default = cand if cand in times else default
    st.session_state[tkey] = default
if st.session_state.pop("advance", False):  # set by the play loop below, applied before the slider exists
    st.session_state[tkey] = times[(times.index(st.session_state[tkey]) + PLAY_STEP) % len(times)]

c_time, c_play = st.columns([8, 1])
t_sel = c_time.select_slider("Time", options=times, key=tkey, format_func=lambda ts: f"{ts:%H:%M}")
play = c_play.toggle("Play", key="play")

df_t = df[df.t == t_sel]
link_state = {r.link_id: dict(up=bool(r.up), load_gbps=float(r.load_gbps), utilization=float(r.utilization))
              for r in df_t.itertuples()}
factor = hourly_factor(topo.profile, meta["profile"], t_sel.to_pydatetime())
node_demand = {k: v * factor for k, v in node_peak_demand(topo).items()}
site_counts = {g.parent: g.k12_sites + g.higher_ed_sites + g.healthcare_sites for g in topo.sites}

left, right = st.columns([4, 4])
selected = None if inspect == "-" else inspect
with left:
    fig = build_map(topo, link_state, node_demand, site_counts, tier_mode, classes, emphasize, selected or st.session_state.get("clicked"), show_labels)
    event = st.plotly_chart(fig, width="content", on_select="rerun", selection_mode="points", key="map")
    clicked = next((p["customdata"] for p in event.selection.points if p.get("customdata") in nodes), None) if event else None
    st.session_state["clicked"] = clicked
with right:
    st.caption(f"Simulated {DAY_LABEL.get(meta['profile'], meta['profile'])}, {t_sel:%H:%M}  |  "
               "sites, demand and latencies are assumptions")
    kpi_tiles(kpi_values(df_t))
    top_links_table(top_links_frame(df_t, topo))
    node_id = selected or clicked
    if node_id:
        st.divider()
        node_detail(topo, node_id, link_state, node_demand)

if play:
    time.sleep(0.4)
    st.session_state["advance"] = True
    st.rerun()
