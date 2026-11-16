"""Demand model: node peak demand, gravity-model traffic matrix, time-of-day scaling.

Gbps = gigabits per second. A "demand matrix" lists, for each pair of nodes, how much traffic
flows between them. Link direction is ignored: a pair's volume counts once on every link it crosses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .schema import SiteGroup, TrafficProfile
from .topology import Topology


@dataclass(frozen=True)
class DemandMatrix:
    """Traffic volume (Gbps) for each (src, dst) node pair, in a fixed pair order."""

    pairs: tuple[tuple[str, str], ...]
    gbps: np.ndarray

    def scaled(self, factor: float | np.ndarray) -> DemandMatrix:
        return DemandMatrix(self.pairs, self.gbps * factor)

    @property
    def total_gbps(self) -> float:
        return float(self.gbps.sum())


def group_peak_demand_gbps(node_id: str, g: SiteGroup, prof: TrafficProfile) -> float:
    """peak demand = sum over site types of (count x unit demand x concurrency)."""
    u, c = prof.unit_demand_gbps, prof.concurrency
    campus = prof.higher_ed_campus_gbps_by_node.get(node_id, u.higher_ed_gbps_per_campus)
    return (
        g.k12_sites * u.k12_gbps_per_site * c.k12
        + g.healthcare_sites * u.healthcare_gbps_per_site * c.healthcare
        + g.higher_ed_sites * campus * c.higher_ed
    )


def node_peak_demand(topo: Topology) -> dict[str, float]:
    """Peak demand per node id (only nodes with sites behind them)."""
    out: dict[str, float] = {}
    for g in topo.sites:
        out[g.parent] = out.get(g.parent, 0.0) + group_peak_demand_gbps(g.parent, g, topo.profile)
    return {k: v for k, v in out.items() if v > 0}


def build_peak_matrix(topo: Topology, demand: dict[str, float] | None = None) -> DemandMatrix:
    """Peak-hour matrix. Each node sends `internet_share` of its demand to/from the internet exit;
    the rest is shared between node pairs in proportion to demand_i * demand_j (gravity model),
    with each pair flow serving two endpoints."""
    prof = topo.profile
    d = demand if demand is not None else node_peak_demand(topo)
    exit_node = prof.internet_exit_node
    ids = sorted(d)
    pairs: list[tuple[str, str]] = []
    vols: list[float] = []
    for i in ids:
        if i != exit_node:
            pairs.append((i, exit_node))
            vols.append(prof.internet_share * d[i])
    peers = [i for i in ids if i != exit_node]
    weights = {(a, b): d[a] * d[b] for k, a in enumerate(peers) for b in peers[k + 1:]}
    wsum = sum(weights.values())
    total_inter = (1 - prof.internet_share) * sum(d[i] for i in peers) / 2
    for pair, w in weights.items():
        pairs.append(pair)
        vols.append(total_inter * w / wsum if wsum else 0.0)
    return DemandMatrix(tuple(pairs), np.array(vols))


def hourly_factor(prof: TrafficProfile, profile_name: str, t: datetime) -> float:
    """Time-of-day multiplier, linearly interpolated between the hourly values."""
    table = prof.hourly_factor[profile_name]
    x = t.hour + t.minute / 60.0
    h = int(x)
    frac = x - h
    return table[h] * (1 - frac) + table[(h + 1) % 24] * frac


def add_noise(m: DemandMatrix, rng: np.random.Generator, pct: float) -> DemandMatrix:
    return m.scaled(rng.uniform(1 - pct, 1 + pct, size=m.gbps.shape))
