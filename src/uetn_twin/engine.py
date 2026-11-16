"""Fixed-step simulation loop, Parquet output, summaries and the single-point-of-failure (SPOF) report."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .backend.base import NetworkBackend
from .backend.flow import FlowBackend
from .schema import Snapshot
from .topology import Topology
from .traffic import add_noise, build_peak_matrix, hourly_factor, node_peak_demand

# Gateway of the eastern 20G ring: the whole ring hangs off this one link, so it is a modeled bottleneck.
EAST_GATEWAY = "uvu-orem--uvu-wasatch"
# Override with UETN_TWIN_OUTPUTS to keep run outputs outside the project (e.g. away from a synced folder).
DEFAULT_OUT = Path(os.environ.get("UETN_TWIN_OUTPUTS", Path(__file__).resolve().parents[2] / "outputs"))
DEFAULT_START = datetime(2026, 11, 16, 0, 0)  # a Monday


@dataclass
class RunResult:
    snapshots: list[Snapshot]
    total_demand_gbps: list[float]  # offered traffic at each step
    profile_name: str
    step_minutes: int
    seed: int


def make_backend(topo: Topology) -> NetworkBackend:
    b = FlowBackend()
    b.load(topo)
    return b


def run_simulation(topo: Topology, hours: float = 24, start: datetime = DEFAULT_START,
                   profile_name: str = "weekday_semester", backend: NetworkBackend | None = None) -> RunResult:
    prof = topo.profile
    if profile_name not in prof.hourly_factor:
        raise ValueError(f"unknown profile '{profile_name}'; choose from {sorted(prof.hourly_factor)}")
    backend = backend or make_backend(topo)
    peak = build_peak_matrix(topo)
    rng = np.random.default_rng(prof.seed)
    steps = int(hours * 60 / prof.step_minutes)
    snaps, totals = [], []
    for k in range(steps):
        t = start + timedelta(minutes=k * prof.step_minutes)
        m = add_noise(peak.scaled(hourly_factor(prof, profile_name, t)), rng, prof.noise_pct)
        backend.apply_demand(m)
        snaps.append(backend.observe(t))
        totals.append(m.total_gbps)
    return RunResult(snaps, totals, profile_name, prof.step_minutes, prof.seed)


def to_frame(topo: Topology, run: RunResult) -> pd.DataFrame:
    """One row per (time, link)."""
    classes = {ln.id: ln.link_class.value for ln in topo.links}
    caps = {ln.id: ln.capacity_gbps for ln in topo.links}
    rows = []
    for s, total in zip(run.snapshots, run.total_demand_gbps):
        unreach = json.dumps(s.unreachable_nodes)
        for ls in s.links:
            rows.append((s.t, ls.link_id, classes[ls.link_id], caps[ls.link_id], ls.up, ls.load_gbps,
                         ls.utilization, ls.flows, total, unreach, s.affected_sites))
    return pd.DataFrame(rows, columns=["t", "link_id", "link_class", "capacity_gbps", "up", "load_gbps",
                                       "utilization", "flows", "total_demand_gbps", "unreachable_nodes",
                                       "affected_sites"])


def write_run(topo: Topology, run: RunResult, out_base: Path = DEFAULT_OUT) -> Path:
    out = out_base / f"run_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True)
    to_frame(topo, run).to_parquet(out / "snapshots.parquet", index=False)
    meta = dict(profile=run.profile_name, step_minutes=run.step_minutes, seed=run.seed,
                start=run.snapshots[0].t.isoformat(), steps=len(run.snapshots),
                internet_exit_node=topo.profile.internet_exit_node, internet_share=topo.profile.internet_share,
                total_peak_demand_gbps=sum(node_peak_demand(topo).values()))
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return out


def east_demand_gbps(topo: Topology) -> tuple[list[str], float]:
    """Nodes cut off from the internet exit if the eastern gateway fails, and their summed peak demand."""
    b = make_backend(topo)
    b.apply_demand(build_peak_matrix(topo))
    b.set_link_state(EAST_GATEWAY, False)
    nodes = b.observe(DEFAULT_START).unreachable_nodes
    d = node_peak_demand(topo)
    return nodes, sum(d.get(n, 0.0) for n in nodes)


def summarize(topo: Topology, run: RunResult, top: int = 10) -> str:
    df = to_frame(topo, run)
    g = df.groupby("link_id")
    mx = g["utilization"].max().sort_values(ascending=False)
    at = df.loc[df.groupby("link_id")["utilization"].idxmax()].set_index("link_id")
    lines = [f"Profile {run.profile_name}, {len(run.snapshots)} steps of {run.step_minutes} min",
             f"Total peak demand assumption (sum over nodes): {sum(node_peak_demand(topo).values()):.1f} Gbps; "
             f"max offered traffic in run: {max(run.total_demand_gbps):.1f} Gbps", "",
             f"Top {top} links by peak utilization:",
             f"{'link':44s} {'class':15s} {'cap Gbps':>8s} {'max load':>9s} {'max util':>8s}  at"]
    for lid in mx.index[:top]:
        r = at.loc[lid]
        lines.append(f"{lid:44s} {r.link_class:15s} {r.capacity_gbps:8.1f} {r.load_gbps:9.2f} {mx[lid]:8.1%}  {r.t:%a %H:%M}")
    over = mx[mx > 1.0]
    lines.append("")
    lines.append(f"Links above 100% utilization: {len(over)}" + (f" -> {list(over.index)}" if len(over) else ""))
    lines.append(f"Links above 80% utilization: {int((mx > 0.8).sum())}")
    if EAST_GATEWAY in mx.index:
        nodes, dem = east_demand_gbps(topo)
        lines.append(f"Eastern gateway {EAST_GATEWAY}: peak utilization {mx[EAST_GATEWAY]:.1%}; "
                     f"eastern peak demand behind it {dem:.2f} Gbps ({len(nodes)} nodes)")
    unreach = sorted({n for s in run.snapshots for n in s.unreachable_nodes})
    lines.append(f"Unreachable nodes during run: {unreach or 'none'}")
    return "\n".join(lines)


def spof_table(topo: Topology) -> pd.DataFrame:
    """For each link: what breaks if it alone fails, at weekday peak (no noise).

    unreachable_nodes / affected_sites: cut off from the internet exit.
    overloaded_after_reroute: links above 100% utilization once traffic reroutes.
    """
    b = make_backend(topo)
    b.apply_demand(build_peak_matrix(topo))
    base_over = {ls.link_id for ls in b.observe(DEFAULT_START).links if ls.utilization > 1.0}
    rows = []
    for ln in topo.links:
        b.set_link_state(ln.id, False)
        s = b.observe(DEFAULT_START)
        b.set_link_state(ln.id, True)
        over = sorted({ls.link_id for ls in s.links if ls.utilization > 1.0} - base_over)
        rows.append(dict(link=ln.id, link_class=ln.link_class.value, capacity_gbps=ln.capacity_gbps,
                         unreachable_nodes=len(s.unreachable_nodes), affected_sites=s.affected_sites,
                         overloaded_after_reroute=len(over), overloaded_list=over, unreachable=",".join(s.unreachable_nodes[:4])
                         + ("..." if len(s.unreachable_nodes) > 4 else ""), overloaded=",".join(over[:3])
                         + ("..." if len(over) > 3 else "")))
    df = pd.DataFrame(rows).sort_values(["affected_sites", "overloaded_after_reroute", "unreachable_nodes"],
                                        ascending=False, kind="stable")
    df.attrs["baseline_overloaded"] = sorted(base_over)
    return df.reset_index(drop=True)
