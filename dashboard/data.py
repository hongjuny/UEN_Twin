"""Reads v1 run directories (outputs/run_<scenario>_<time>/) for the dashboard. No Streamlit imports here.

A finished run is read from its Parquet export (cached, it never changes). A run in progress is read from
telemetry.sqlite (WAL mode: the simulator writes while this reads). Everything is SIMULATED.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

from uetn_twin.sim.clock import SimClock
from uetn_twin.sim.scenario import Scenario
from uetn_twin.topology import Topology

WEEKDAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@lru_cache(maxsize=64)
def _parquet(path: str, table: str) -> pd.DataFrame:
    return pd.read_parquet(Path(path) / f"{table}.parquet")


def read_meta(path: Path) -> dict | None:
    try:
        return json.loads((Path(path) / "run_meta.json").read_text())
    except (OSError, json.JSONDecodeError):  # missing, or caught mid-write
        return None


def run_status(path: Path, meta: dict) -> str:
    """running | finished | interrupted | stalled (marked running but nothing written for a while)."""
    status = meta.get("status", "finished" if meta.get("finished") else "running")
    if status != "running":
        return status
    speed = meta.get("speed") or 1
    patience = max(30.0, 4 * meta.get("telemetry_s", 30) / speed)
    stamps = [f.stat().st_mtime for f in (Path(path) / "telemetry.sqlite", Path(path) / "telemetry.sqlite-wal") if f.exists()]
    if not stamps or time.time() - max(stamps) > patience:
        return "stalled"
    return "running"


def list_runs(out_dir: Path) -> list[dict]:
    """v1 runs (those with run_meta.json), newest first: {name, scenario, status, speed}."""
    runs = []
    for p in sorted(Path(out_dir).glob("run_*"), reverse=True):
        meta = read_meta(p)
        if meta is None:
            continue
        runs.append(dict(name=p.name, scenario=meta["scenario"]["id"], status=run_status(p, meta), speed=meta.get("speed")))
    return runs


class RunData:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.meta = read_meta(self.path) or {}
        self.status = run_status(self.path, self.meta)
        self.scenario = Scenario.model_validate(self.meta["scenario"])
        self.clock = SimClock(self.scenario.day, self.scenario.start)
        self.duration_s = float(self.meta["duration_s"])
        self.telemetry_s = float(self.meta.get("telemetry_s", 30))
        # a finished run has the immutable Parquet export; anything else is read live from SQLite
        self.use_parquet = self.status in ("finished", "interrupted") and (self.path / "totals.parquet").exists()

    def refresh(self) -> RunData:
        return RunData(self.path)

    def _table(self, table: str, where: str = "", params: tuple = (), pandas_filter=None) -> pd.DataFrame:
        if self.use_parquet:
            df = _parquet(str(self.path), table)
            return pandas_filter(df) if pandas_filter else df
        conn = sqlite3.connect(self.path / "telemetry.sqlite", timeout=5)
        try:
            df = pd.read_sql(f"SELECT * FROM {table} {where}", conn, params=params)
        finally:
            conn.close()
        if table in ("link_telemetry", "link_class_telemetry"):
            df.insert(3, "direction", df.from_node + "->" + df.to_node)
        return df

    # ---- queries ----
    def times(self) -> list[float]:
        """Simulated seconds (since the scenario start) of every recorded telemetry interval."""
        return sorted(self._table("totals")["sim_s"].unique().tolist())

    def at(self, sim_s: float) -> dict:
        links = self._table("link_telemetry", "WHERE sim_s = ?", (sim_s,), lambda d: d[d.sim_s == sim_s])
        nodes = self._table("node_telemetry", "WHERE sim_s = ?", (sim_s,), lambda d: d[d.sim_s == sim_s])
        totals = self._table("totals", "WHERE sim_s = ?", (sim_s,), lambda d: d[d.sim_s == sim_s])
        return dict(links=links, nodes=nodes, totals=totals.iloc[0])

    def link_series(self, link_id: str, since: float, until: float) -> pd.DataFrame:
        return self._table("link_telemetry", "WHERE link_id = ? AND sim_s BETWEEN ? AND ?", (link_id, since, until),
                           lambda d: d[(d.link_id == link_id) & d.sim_s.between(since, until)])

    def class_series(self, link_id: str, from_node: str, since: float, until: float) -> pd.DataFrame:
        return self._table("link_class_telemetry", "WHERE link_id = ? AND from_node = ? AND sim_s BETWEEN ? AND ?",
                           (link_id, from_node, since, until),
                           lambda d: d[(d.link_id == link_id) & (d.from_node == from_node) & d.sim_s.between(since, until)])

    def node_series(self, node_id: str, since: float, until: float) -> pd.DataFrame:
        return self._table("node_telemetry", "WHERE node_id = ? AND sim_s BETWEEN ? AND ?", (node_id, since, until),
                           lambda d: d[(d.node_id == node_id) & d.sim_s.between(since, until)])

    def totals_frame(self) -> pd.DataFrame:
        return self._table("totals")

    def events(self) -> pd.DataFrame:
        df = self._table("events").copy()
        df["payload"] = df.payload.map(lambda p: json.loads(p) if isinstance(p, str) else p)
        return df

    def down_links(self, sim_s: float) -> set[str]:
        down: set[str] = set()
        ev = self.events()
        for r in ev[(ev.type == "set_link_state") & (ev.sim_s <= sim_s)].itertuples():
            (down.discard if r.payload["up"] else down.add)(r.payload["link"])
        return down

    # ---- time labels (weekday and clock only; the calendar date is a placeholder and never shown) ----
    def label(self, sim_s: float) -> str:
        ts = self.clock.at(sim_s)
        return f"{WEEKDAY_ABBR[ts.weekday()]} {ts:%H:%M}"

    def clock_of(self, sim_s: float) -> datetime:
        return self.clock.at(sim_s)


# ---- overlays -----------------------------------------------------------------------------------------------

@dataclass
class OverlayInfo:
    label: str
    cls: str
    start_s: float
    end_s: float
    status: str  # upcoming | active | ended


def session_nodes(run: RunData) -> list[str]:
    """Nodes targeted by overlays that add server sessions (empty when the scenario has none)."""
    from uetn_twin import topology
    from uetn_twin.sim.scenario import node_regions, resolve

    topo = topology.load()
    region_of = node_regions(topo)
    out: list[str] = []
    for ov in run.scenario.overlays:
        if ov.targets is not None and "sessions" in ov.affects:
            out += [n for n in resolve(ov.targets, topo, region_of) if n not in out]
    return out


def overlay_infos(run: RunData, now_s: float) -> list[OverlayInfo]:
    out = []
    for ov in run.scenario.overlays:
        _, a, b = ov.shape.compile(run.clock)
        status = "upcoming" if now_s < a else ("ended" if now_s >= b else "active")
        out.append(OverlayInfo(ov.label or ov.cls, ov.cls, a, b, status))
    return sorted(out, key=lambda o: o.start_s)


# ---- map, table and KPI inputs --------------------------------------------------------------------------------

def link_state(links: pd.DataFrame, down: set[str]) -> dict[str, dict]:
    """link_id -> {up, load_gbps, utilization, dirs}. The map colors by the busier direction."""
    out: dict[str, dict] = {}
    for lid, g in links.groupby("link_id"):
        worst = g.loc[g.utilization.idxmax()]
        out[lid] = dict(
            up=lid not in down, load_gbps=float(worst.gbps), utilization=float(worst.utilization),
            dirs=[dict(frm=r.from_node, to=r.to_node, gbps=float(r.gbps), utilization=float(r.utilization),
                       dropped=float(r.dropped_gbps), latency_ms=float(r.latency_ms)) for r in g.itertuples()])
    return out


def node_session_util(nodes: pd.DataFrame) -> dict[str, float]:
    return dict(zip(nodes.node_id, nodes.session_utilization.astype(float)))


def kpi_values(links: pd.DataFrame, nodes: pd.DataFrame, totals: pd.Series, site_counts: dict[str, int]) -> dict:
    by_link = links.groupby("link_id").utilization.max()
    unreachable = nodes[nodes.unreachable > 0.5].node_id
    return dict(
        total_gbps=float(totals.generated_gbps),
        max_util=float(by_link.max()), max_util_link=str(by_link.idxmax()),
        n_over_80=int((by_link > 0.8).sum()),
        dropped_gbps=float(totals.dropped_gbps),
        unreachable_sites=int(sum(site_counts.get(n, 0) for n in unreachable)),
    )


def top_links_frame(links: pd.DataFrame, topo: Topology, n: int = 10) -> pd.DataFrame:
    """The n busiest link directions."""
    info = {ln.id: ln for ln in topo.links}
    nodes = topo.node_map()
    out = links.sort_values("utilization", ascending=False).head(n)
    return pd.DataFrame({
        "Link": out.link_id.values,
        "Direction": [f"{a} > {b}" for a, b in zip(out.from_node, out.to_node)],
        "Cap (G)": [info[x].capacity_gbps for x in out.link_id],
        "Load (G)": out.gbps.round(2).values,
        "Util": (out.utilization * 100).round().astype(int).values,
        "Drop (G)": out.dropped_gbps.round(2).values,
        "Source": [info[x].confidence for x in out.link_id],
    })


def window(now_s: float, hours: float = 2.0) -> tuple[float, float]:
    return max(0.0, now_s - hours * 3600), now_s


def snap(times: list[float], sim_s: float) -> float:
    return min(times, key=lambda t: abs(t - sim_s))


def default_time(run: RunData, times: list[float]) -> float:
    """The most telling moment: the heaviest-drop interval if anything is dropped, else the busiest interval."""
    totals = run.totals_frame()
    col = totals.dropped_gbps if totals.dropped_gbps.max() > 0 else totals.generated_gbps
    return snap(times, float(totals.loc[col.idxmax()].sim_s))
