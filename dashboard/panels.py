"""Side panels: KPI tiles, top-utilization link table, node detail.

The computations are plain functions on DataFrames/Topology so they can be tested without Streamlit.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from uetn_twin.topology import Topology
from uetn_twin.traffic import group_peak_demand_gbps


def kpi_values(df_t: pd.DataFrame) -> dict:
    """df_t: the snapshot rows (one per link) for a single time step."""
    worst = df_t.loc[df_t.utilization.idxmax()]
    return dict(
        total_gbps=float(df_t.total_demand_gbps.iloc[0]),
        max_util=float(worst.utilization),
        max_util_link=str(worst.link_id),
        n_over_80=int((df_t.utilization > 0.8).sum()),
        unreachable_sites=int(df_t.affected_sites.iloc[0]),
    )


def top_links_frame(df_t: pd.DataFrame, topo: Topology, n: int = 10) -> pd.DataFrame:
    conf = {ln.id: ln.confidence for ln in topo.links}
    out = df_t.sort_values("utilization", ascending=False).head(n)
    return pd.DataFrame({
        "Link": out.link_id.values,
        "Class": [c.replace("backbone_", "bb ").replace("ethernet_", "eth ") for c in out.link_class],
        "Cap (G)": out.capacity_gbps.values,
        "Load (G)": out.load_gbps.round(2).values,
        "Util": (out.utilization * 100).round().astype(int).values,
        "Source": [conf[x] for x in out.link_id],
    })


def kpi_tiles(k: dict) -> None:
    a, b = st.columns(2)
    a.metric("Total traffic", f"{k['total_gbps']:.1f} Gbps")
    b.metric("Max link utilization", f"{k['max_util']:.0%}", help=k["max_util_link"])
    c, d = st.columns(2)
    c.metric("Links above 80%", k["n_over_80"])
    d.metric("Unreachable sites", k["unreachable_sites"])
    d.caption("Active once v1 failure scenarios are introduced")


def top_links_table(frame: pd.DataFrame) -> None:
    st.markdown("**Most utilized links**")
    st.dataframe(
        frame, hide_index=True, width="stretch",
        column_config={
            "Util": st.column_config.NumberColumn("Util", format="%d%%", width="small"),
            "Source": st.column_config.TextColumn("Source", help="Where the link comes from: map / inferred / assumed (capacity is an estimate unless map)", width="small"),
            "Link": st.column_config.TextColumn("Link", width="medium"),
            "Class": st.column_config.TextColumn("Class", width="small"),
            "Cap (G)": st.column_config.NumberColumn("Cap (G)", help="Capacity in Gbps", width="small"),
            "Load (G)": st.column_config.NumberColumn("Load (G)", help="Load in Gbps", width="small"),
        },
    )


def node_detail(topo: Topology, node_id: str, link_state: dict[str, dict], node_demand: dict[str, float]) -> None:
    n = topo.node_map()[node_id]
    st.markdown(f"**{n.name}**  ({n.tier}, {n.kind}, {n.city})")
    st.caption(f"Source: {n.confidence}" + (f" - {n.notes}" if n.notes else ""))
    groups = [g for g in topo.sites if g.parent == node_id]
    if groups:
        g = groups[0]
        peak = group_peak_demand_gbps(node_id, g, topo.profile)
        st.write(
            f"Sites behind this node (assumed): {g.k12_sites} K-12, {g.higher_ed_sites} higher-ed, "
            f"{g.healthcare_sites} healthcare. Peak demand {peak:.2f} Gbps, now {node_demand.get(node_id, 0):.2f} Gbps."
        )
    else:
        st.write("No sites behind this node.")
    nodes = topo.node_map()
    rows = []
    for ln in topo.links:
        if node_id in (ln.a, ln.b):
            other = ln.b if ln.a == node_id else ln.a
            s = link_state.get(ln.id, {})
            rows.append({"Neighbor": nodes[other].name, "Class": ln.link_class.value.replace("backbone_", "bb ").replace("ethernet_", "eth "),
                         "Cap (G)": ln.capacity_gbps, "Util": round(s.get("utilization", 0.0) * 100) if s.get("up", True) else None, "Source": ln.confidence})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Util": st.column_config.NumberColumn("Util", format="%d%%")})
