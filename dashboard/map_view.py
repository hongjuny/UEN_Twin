"""Plotly map of the Utah backbone: links colored by utilization, nodes by tier.

Uses scattergeo (no tile server, supports square markers and dashed lines). scope="usa" + mercator crashes
Plotly.js, so scope "north america" is used; state borders still draw. Nodes in the same city share
coordinates, so for display only they are spread on a small ring; data coordinates are untouched.
"""

from __future__ import annotations

from collections import defaultdict
from math import cos, pi, sin

import plotly.graph_objects as go

from uetn_twin.topology import Topology

LAT_RANGE = [36.9, 42.1]
LON_RANGE = [-114.1, -108.9]

# line width in px by link class (400G thickest)
CLASS_WIDTH = {
    "backbone_400g": 7, "backbone_100g": 5.5, "backbone_40g": 4.5, "backbone_20g": 3.5,
    "ethernet_10g": 2.5, "ethernet_1g": 2, "microwave_200m": 1.5, "ethernet_sub1g": 1.5,
}
# Discrete utilization bands (workorder section 7): <60% green, 60-85% yellow, 85-100% orange, >=100% red.
# Operators read steps more easily than a gradient. Upper bound of each band, then color.
BANDS = [(0.6, "#2e9e5b"), (0.85, "#e6c229"), (1.0, "#f08a24"), (float("inf"), "#d62728")]
CMAX = 1.2  # colorbar range (so the red band has visible height)
DOWN_COLOR = "#8a8a8a"
MAP_HEIGHT = 740
MAP_WIDTH = 560  # fixed so the map fills the figure and overlay positions (legend, colorbar) line up with it
# Short on-map labels for core nodes (one label per co-located group, e.g. the 4 Salt Lake PoPs).
LABELS = {
    "usu-logan": "USU", "wsu-ogden": "WSU", "slc-slcc": "SLC", "uvu-orem": "UVU", "uvu-wasatch": "Wasatch",
    "richfield-dc": "Richfield", "suu-cedar": "SUU", "tdc-stgeorge": "TDC", "ubtc-vernal": "Vernal",
    "ubtc-roosevelt": "Roosevelt", "usu-eastern": "Price", "moab": "Moab", "usu-blanding": "Blanding",
    "wendover": "Wendover", "park-city": "Park City", "tooele-tc": "Tooele",
}
# label -> (lat offset, lon offset in degrees from the group's city center, text position): hand-placed to avoid
# markers, lines and the map edge
LABEL_SPEC = {
    "USU": (0.0, -0.22, "middle left"), "WSU": (0.0, -0.22, "middle left"), "SLC": (0.22, -0.12, "middle left"),
    "UVU": (-0.12, 0.2, "middle right"), "Wasatch": (-0.2, 0.05, "middle right"), "Park City": (0.12, 0.12, "middle right"),
    "Richfield": (0.0, -0.22, "middle left"), "SUU": (0.0, -0.22, "middle left"), "TDC": (0.22, -0.2, "middle left"),
    "Vernal": (0.17, 0.0, "middle center"), "Roosevelt": (-0.17, -0.05, "middle center"), "Price": (0.14, 0.2, "middle right"),
    "Moab": (0.0, -0.22, "middle left"), "Blanding": (-0.15, 0.0, "middle center"), "Wendover": (0.15, 0.1, "middle right"),
    "Tooele": (-0.15, 0.0, "middle center"),
}
RING_DEG = 0.04  # display-only spread for co-located nodes


def _line_row(width_px: float, label: str) -> str:
    return f'<span style="font-size:{int(6 + 2.2 * width_px)}px">\u2501\u2501</span> {label}'


LEGEND_TEXT = "<br>".join([
    "<b>Nodes</b>",
    '<span style="color:#1f2a44">\u25a0</span> core (read from map)',
    '<span style="color:#9aa0ab">\u25a0</span> core, inferred (faded)',
    "\u25cb distribution",
    "<b>Line width = link class</b>",
    *[_line_row(CLASS_WIDTH[c], lab) for c, lab in [("backbone_400g", "400G"), ("backbone_100g", "100G"), ("backbone_40g", "40G"),
                                                    ("backbone_20g", "20G"), ("ethernet_10g", "10G"), ("ethernet_1g", "1G")]],
])


def util_band(u: float) -> int:
    return next(k for k, (hi, _) in enumerate(BANDS) if u < hi)


def display_positions(topo: Topology) -> dict[str, tuple[float, float]]:
    """Plot positions. DISPLAY ONLY: nodes sharing a city are spread on a small ring so they stay
    visible and clickable; the coordinates in the data are never changed."""
    groups: dict[tuple[float, float], list[str]] = defaultdict(list)
    for n in topo.nodes:
        groups[(n.lat, n.lon)].append(n.id)
    pos = {}
    for (lat, lon), ids in groups.items():
        if len(ids) == 1:
            pos[ids[0]] = (lat, lon)
            continue
        for k, nid in enumerate(sorted(ids)):
            ang = 2 * pi * k / len(ids)
            pos[nid] = (lat + RING_DEG * sin(ang), lon + RING_DEG * 1.3 * cos(ang))
    return pos


def group_labels(topo: Topology, shown: set[str]) -> list[tuple[float, float, str, str]]:
    """(lat, lon, text, text position) with one label per group of nodes that share data coordinates."""
    groups: dict[tuple[float, float], list[str]] = defaultdict(list)
    for n in topo.nodes:
        if n.id in shown:
            groups[(n.lat, n.lon)].append(n.id)
    out = []
    for (lat, lon), ids in groups.items():
        text = next((LABELS[i] for i in sorted(ids) if i in LABELS), None)
        if text:
            dlat, dlon, pos = LABEL_SPEC[text]
            out.append((lat + dlat, lon + dlon, text, pos))
    return out


def build_map(topo: Topology, link_state: dict[str, dict], node_demand: dict[str, float],
              site_counts: dict[str, int], tier_mode: str = "core+distribution",
              link_classes: set[str] | None = None, emphasize_nonmap: bool = False,
              selected_node: str | None = None, show_labels: bool = True) -> go.Figure:
    """link_state: link_id -> {up, load_gbps, utilization}. tier_mode: core | core+distribution | all."""
    nodes = topo.node_map()
    pos = display_positions(topo)
    tiers = {"core": {"core"}, "core+distribution": {"core", "distribution"}, "all": {"core", "distribution", "external"}}[tier_mode]
    shown = {i for i, n in nodes.items() if n.tier in tiers}
    link_classes = link_classes if link_classes is not None else {ln.link_class.value for ln in topo.links}

    # ---- links: one trace per (width, color bin, opacity, up) ----
    groups: dict[tuple, tuple[list, list]] = defaultdict(lambda: ([], []))
    hover_lat, hover_lon, hover_txt = [], [], []
    for ln in topo.links:
        if ln.a not in shown or ln.b not in shown or ln.link_class.value not in link_classes:
            continue
        st = link_state.get(ln.id, {"up": True, "load_gbps": 0.0, "utilization": 0.0})
        up = st["up"]
        band = util_band(st["utilization"])
        opacity = 0.4 if ln.confidence == "assumed" else (0.65 if emphasize_nonmap and ln.confidence == "inferred" else 1.0)
        key = (CLASS_WIDTH[ln.link_class.value], band if up else -1, opacity)
        lats, lons = groups[key]
        (la, lo), (lb, lob) = pos[ln.a], pos[ln.b]
        lats += [la, lb, None]
        lons += [lo, lob, None]
        hover_lat.append((la + lb) / 2)
        hover_lon.append((lo + lob) / 2)
        state = f"{st['utilization']:.1%} ({st['load_gbps']:.2f} of {ln.capacity_gbps:g} Gbps)" if up else "DOWN"
        hover_txt.append(f"<b>{nodes[ln.a].name} - {nodes[ln.b].name}</b><br>{ln.link_class.value}, {ln.capacity_gbps:g} Gbps"
                         f"<br>utilization: {state}<br>source: {ln.confidence}")

    fig = go.Figure()
    for (width, band, opacity), (lats, lons) in sorted(groups.items(), key=lambda kv: kv[0][1]):
        down = band == -1
        color = DOWN_COLOR if down else BANDS[band][1]
        fig.add_trace(go.Scattergeo(lat=lats, lon=lons, mode="lines", hoverinfo="skip", opacity=opacity,
                                    line=dict(width=width, color=color, dash="dot" if down else "solid"),
                                    showlegend=False))
    fig.add_trace(go.Scattergeo(lat=hover_lat, lon=hover_lon, mode="markers", text=hover_txt, hoverinfo="text",
                                marker=dict(size=10, opacity=0), showlegend=False, name="links"))

    # ---- nodes ----
    for tier, symbol, size in (("distribution", "circle", 6), ("core", "square", 11), ("external", "circle", 7)):
        ids = [i for i in nodes if nodes[i].tier == tier and i in shown]
        if not ids:
            continue
        sel = [i == selected_node for i in ids]
        hover = [
            f"<b>{nodes[i].name}</b><br>{tier}, {nodes[i].kind}, {nodes[i].city}<br>"
            f"sites behind: {site_counts.get(i, 0)}<br>demand now: {node_demand.get(i, 0.0):.2f} Gbps<br>source: {nodes[i].confidence}"
            for i in ids
        ]
        fill = {"core": "#1f2a44", "distribution": "#ffffff", "external": "#9aa0a6"}[tier]
        fig.add_trace(go.Scattergeo(
            lat=[pos[i][0] for i in ids], lon=[pos[i][1] for i in ids], mode="markers", customdata=ids,
            text=hover, hoverinfo="text", name=tier, showlegend=False,
            marker=dict(symbol=symbol, size=[size + 5 if s else size for s in sel], color=fill,
                        opacity=[1.0 if nodes[i].confidence == "map" else 0.6 for i in ids],
                        line=dict(width=[3 if s else 1.2 for s in sel], color=["#e4572e" if s else "#1f2a44" for s in sel]))))

    if show_labels:
        lab = group_labels(topo, shown)
        fig.add_trace(go.Scattergeo(
            lat=[x[0] for x in lab], lon=[x[1] for x in lab], mode="text", hoverinfo="skip", showlegend=False,
            text=[f"<b>{x[2]}</b>" for x in lab], textposition=[x[3] for x in lab],
            textfont=dict(size=13, color="#1f2a44")))

    # colorbar (dummy trace outside the view): stepped scale with ticks at the band boundaries
    edges = [0.0, 0.6 / CMAX, 0.85 / CMAX, 1.0 / CMAX, 1.0]
    scale = []
    for k, (_, color) in enumerate(BANDS):
        scale += [[edges[k], color], [edges[k + 1], color]]
    fig.add_trace(go.Scattergeo(
        lat=[0, 0], lon=[0, 0], mode="markers", hoverinfo="skip", showlegend=False,
        marker=dict(size=0.1, color=[0, CMAX], cmin=0, cmax=CMAX, showscale=True, colorscale=scale,
                    colorbar=dict(title=dict(text="link utilization", side="top"), tickfont=dict(size=10), tickvals=[0, 0.6, 0.85, 1.0],
                                  ticktext=["0%", "60%", "85%", "100%+"], tickangle=0, orientation="h",
                                  len=0.45, thickness=10, x=0.66, y=0.07, yanchor="middle", xanchor="center"))))

    fig.update_geos(
        scope="north america", projection_type="mercator", lataxis_range=LAT_RANGE, lonaxis_range=LON_RANGE,
        resolution=50, showland=True, landcolor="#f3f1ea", showlakes=True, lakecolor="#dbe9f4",
        showsubunits=True, subunitcolor="#7a7a7a", subunitwidth=1.5, showcountries=False, bgcolor="rgba(0,0,0,0)",
    )
    fig.update_layout(height=MAP_HEIGHT, width=MAP_WIDTH, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)", hoverlabel=dict(align="left"),
                      clickmode="event+select", dragmode="pan")
    fig.add_annotation(
        xref="paper", yref="paper", x=0.995, y=0.995, xanchor="right", yanchor="top", align="left", showarrow=False,
        bgcolor="rgba(255,255,255,0.85)", bordercolor="#9aa0a6", borderwidth=1, borderpad=4, font=dict(size=10, color="#1f2a44"),
        text=LEGEND_TEXT)
    return fig
