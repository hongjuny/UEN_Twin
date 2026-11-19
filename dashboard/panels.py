"""Side panels: KPI tiles, scenario panel, top-utilization link table, node detail. Everything is SIMULATED.

The computations live in data.py as plain functions; this module only draws them.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from uetn_twin.topology import Topology
from uetn_twin.traffic import group_peak_demand_gbps

STATUS_MARK = {"upcoming": "⏳ upcoming", "active": "\U0001f534 active", "ended": "✓ ended"}


def kpi_tiles(k: dict, show_unreachable: bool = False) -> None:
    a, b, c = st.columns(3)
    a.metric("Total traffic", f"{k['total_gbps']:.1f} Gbps")
    b.metric("Max link utilization", f"{k['max_util']:.0%}", help=k["max_util_link"])
    c.metric("Links above 80%", k["n_over_80"])
    d, e, _ = st.columns(3)
    d.metric("Dropped traffic", f"{k['dropped_gbps']:.2f} Gbps", help="Offered load that did not fit (interval average)")
    if show_unreachable:
        e.metric("Unreachable sites", k["unreachable_sites"], help="Sites cut off by a link-state event")


def scenario_panel(run, now_s: float, overlays: list) -> None:
    sc = run.scenario
    st.markdown(f"**{sc.title}**")
    st.caption(" ".join(sc.description.split()))
    st.markdown(f"Simulated time: **{run.label(now_s)}**")
    for o in overlays:
        st.markdown(f"- {run.clock_of(o.start_s):%H:%M} {o.label} ({STATUS_MARK[o.status]})")
    for e in sc.events:
        st.markdown(f"- {e.at} link `{e.link}` {'up' if e.up else 'down'}")


def top_links_table(frame: pd.DataFrame) -> None:
    st.markdown("**Busiest link directions**")
    st.dataframe(
        frame, hide_index=True, width="stretch",
        column_config={
            "Util": st.column_config.NumberColumn("Util", format="%d%%", width="small",
                                                  help="Offered load as a share of capacity; above 100% traffic is dropped"),
            "Source": st.column_config.TextColumn("Source", help="Where the link comes from: map / inferred / assumed", width="small"),
            "Link": st.column_config.TextColumn("Link", width="medium"),
            "Direction": st.column_config.TextColumn("Direction", width="medium"),
            "Cap (G)": st.column_config.NumberColumn("Cap (G)", help="Capacity in Gbps, each direction", width="small"),
            "Load (G)": st.column_config.NumberColumn("Load (G)", width="small"),
            "Drop (G)": st.column_config.NumberColumn("Drop (G)", width="small"),
        },
    )


def node_detail(topo: Topology, node_id: str, link_state: dict[str, dict], node_row: pd.Series | None) -> None:
    n = topo.node_map()[node_id]
    st.markdown(f"**{n.name}**  ({n.tier}, {n.kind}, {n.city})")
    st.caption(f"Source: {n.confidence}" + (f" - {n.notes}" if n.notes else ""))
    groups = [g for g in topo.sites if g.parent == node_id]
    if groups:
        g = groups[0]
        st.write(f"Sites behind this node (assumed): {g.k12_sites} K-12, {g.higher_ed_sites} higher-ed, "
                 f"{g.healthcare_sites} healthcare. Peak demand {group_peak_demand_gbps(node_id, g, topo.profile):.2f} Gbps.")
    else:
        st.write("No sites behind this node.")
    if node_row is not None:
        line = f"Now: {node_row.demand_gbps:.2f} Gbps of owned demand"
        if node_row.server_sessions > 0:
            line += f", {node_row.server_sessions:,.0f} server sessions ({node_row.session_utilization:.0%} of assumed capacity)"
        st.write(line)
    nodes = topo.node_map()
    rows = []
    for ln in topo.links:
        if node_id in (ln.a, ln.b):
            other = ln.b if ln.a == node_id else ln.a
            s = link_state.get(ln.id, {})
            rows.append({"Neighbor": nodes[other].name, "Class": ln.link_class.value.replace("backbone_", "bb ").replace("ethernet_", "eth "),
                         "Cap (G)": ln.capacity_gbps, "Util": round(s.get("utilization", 0.0) * 100) if s.get("up", True) else None,
                         "Source": ln.confidence})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Util": st.column_config.NumberColumn("Util", format="%d%%")})
