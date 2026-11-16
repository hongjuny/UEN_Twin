"""Traffic classes and origin-destination (OD) demand by class.

v1-platform stage 1: the deterministic baseline layer (site demand x class mix x hourly curve). Stochastic layers
(regional wander, bursts) and scenario overlays are multiplied on top of this later.

An OD pair (src, dst) carries traffic flowing FROM src TO dst. Unlike v0, direction matters: a school's
downstream video and its small upstream share are two different pairs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..schema import Confidence
from ..topology import Topology

DEFAULT_CLASSES = Path(__file__).resolve().parents[3] / "data" / "traffic" / "classes.yaml"
SiteType = Literal["k12", "higher_ed", "healthcare"]
Pattern = Literal["exit_to_node", "cache_or_exit_to_node", "exit_and_hospital", "campus_mesh_and_exit", "clients_to_server"]


class ClassSpec(BaseModel):
    """One traffic class. See the comments in data/traffic/classes.yaml for every field."""

    model_config = ConfigDict(extra="forbid")

    description: str
    pattern: Pattern
    toward_node_share: float = Field(ge=0, le=1, description="Share flowing toward the node that owns the demand")
    sessions_per_gbps: float = Field(ge=0, description="Concurrent connections per Gbps")
    priority: int = Field(ge=1, le=5, description="1 = highest; used by intervention tools later")
    mesh_share: float = Field(default=0.5, ge=0, le=1)
    client_exit_share: float = Field(default=0.5, ge=0, le=1)
    hourly: dict[str, list[float]]

    @model_validator(mode="after")
    def _check_hours(self) -> ClassSpec:
        for mode, vals in self.hourly.items():
            if len(vals) != 24:
                raise ValueError(f"hourly.{mode} needs 24 values, got {len(vals)}")
        return self


class TrafficClasses(BaseModel):
    """Contents of data/traffic/classes.yaml. Everything is assumed."""

    model_config = ConfigDict(extra="forbid")

    confidence: Confidence
    research_exit_node: str
    cdn_cache_nodes: list[str]
    cdn_share: float = Field(ge=0, le=1)
    hospital_nodes: list[str]
    site_mix: dict[SiteType, dict[str, float]]
    session_capacity_by_kind: dict[str, int]
    session_capacity_by_node: dict[str, int] = Field(default_factory=dict)
    classes: dict[str, ClassSpec]

    @model_validator(mode="after")
    def _check_mix(self) -> TrafficClasses:
        for site, mix in self.site_mix.items():
            unknown = set(mix) - set(self.classes)
            if unknown:
                raise ValueError(f"site_mix.{site}: unknown classes {sorted(unknown)}")
            if abs(sum(mix.values()) - 1.0) > 1e-9:
                raise ValueError(f"site_mix.{site} must sum to 1, got {sum(mix.values())}")
        return self

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.classes)

    def session_capacity(self, topo: Topology) -> dict[str, int]:
        return {n.id: self.session_capacity_by_node.get(n.id, self.session_capacity_by_kind.get(n.kind, 50000))
                for n in topo.nodes}


def load_classes(path: Path = DEFAULT_CLASSES) -> TrafficClasses:
    return TrafficClasses.model_validate(yaml.safe_load(Path(path).read_text()))


def site_type_peaks(topo: Topology) -> dict[str, dict[str, float]]:
    """node -> site type -> peak demand (Gbps) = sites x unit demand x concurrency, as in v0."""
    u, c = topo.profile.unit_demand_gbps, topo.profile.concurrency
    out: dict[str, dict[str, float]] = {}
    for g in topo.sites:
        campus = topo.profile.higher_ed_campus_gbps_by_node.get(g.parent, u.higher_ed_gbps_per_campus)
        d = out.setdefault(g.parent, {"k12": 0.0, "higher_ed": 0.0, "healthcare": 0.0})
        d["k12"] += g.k12_sites * u.k12_gbps_per_site * c.k12
        d["higher_ed"] += g.higher_ed_sites * campus * c.higher_ed
        d["healthcare"] += g.healthcare_sites * u.healthcare_gbps_per_site * c.healthcare
    return out


def class_peaks(topo: Topology, tc: TrafficClasses) -> dict[str, dict[str, float]]:
    """class -> node -> peak volume (Gbps) when the class's hourly curve is 1.0."""
    out: dict[str, dict[str, float]] = {name: {} for name in tc.names}
    for node, types in site_type_peaks(topo).items():
        for site, gbps in types.items():
            for name, share in tc.site_mix.get(site, {}).items():
                if gbps * share > 0:
                    out[name][node] = out[name].get(node, 0.0) + gbps * share
    return out


def curve_value(values: list[float], t: datetime) -> float:
    x = t.hour + t.minute / 60.0 + t.second / 3600.0
    h = int(x)
    frac = x - h
    return values[h] * (1 - frac) + values[(h + 1) % 24] * frac


def baseline_volumes(topo: Topology, tc: TrafficClasses, mode: str, t: datetime) -> dict[str, dict[str, float]]:
    """class -> node -> volume at time t under an academic mode (weekday_semester / weekend / break)."""
    peaks = class_peaks(topo, tc)
    return {name: {n: v * curve_value(tc.classes[name].hourly[mode], t) for n, v in peaks[name].items()}
            for name in tc.names}


@dataclass(frozen=True)
class ODDemand:
    """Directed demand: gbps[p, c] is class c traffic flowing from pairs[p][0] to pairs[p][1]."""

    pairs: tuple[tuple[str, str], ...]
    classes: tuple[str, ...]
    gbps: np.ndarray

    @property
    def total_gbps(self) -> float:
        return float(self.gbps.sum())

    def only(self, *names: str) -> ODDemand:
        keep = np.array([c in names for c in self.classes])
        return ODDemand(self.pairs, self.classes, self.gbps * keep)

    def scaled(self, factor: float | np.ndarray) -> ODDemand:
        return ODDemand(self.pairs, self.classes, self.gbps * factor)


def build_od(topo: Topology, tc: TrafficClasses, volumes: dict[str, dict[str, float]]) -> ODDemand:
    """Spread each (class, node) volume over directed OD pairs according to the class pattern."""
    exit_node = topo.profile.internet_exit_node
    names = tc.names
    acc: dict[tuple[str, str], np.ndarray] = {}

    def add(src: str, dst: str, ci: int, v: float) -> None:
        if src != dst and v > 0:  # traffic that stays inside one node never crosses a link
            acc.setdefault((src, dst), np.zeros(len(names)))[ci] += v

    def exchange(owner: str, other: str, ci: int, v: float, toward: float) -> None:
        add(other, owner, ci, v * toward)
        add(owner, other, ci, v * (1 - toward))

    node_total: dict[str, float] = {}
    for vols in volumes.values():
        for n, v in vols.items():
            node_total[n] = node_total.get(n, 0.0) + v

    for ci, name in enumerate(names):
        spec = tc.classes[name]
        vols = {n: v for n, v in volumes.get(name, {}).items() if v > 0}
        tw = spec.toward_node_share
        for n, v in vols.items():
            if spec.pattern == "exit_to_node":
                exchange(n, exit_node, ci, v, tw)
            elif spec.pattern == "cache_or_exit_to_node":
                caches = tc.cdn_cache_nodes
                for cache in caches:
                    exchange(n, cache, ci, v * tc.cdn_share / len(caches), tw)
                exchange(n, exit_node, ci, v * (1 - tc.cdn_share if caches else 1.0), tw)
            elif spec.pattern == "exit_and_hospital":
                hubs = [h for h in tc.hospital_nodes if h != n]
                hub_part = 0.5 if hubs else 0.0
                exchange(n, exit_node, ci, v * (1 - hub_part), tw)
                for h in hubs:
                    exchange(n, h, ci, v * hub_part / len(hubs), tw)
            elif spec.pattern == "campus_mesh_and_exit":
                others = {m: w for m, w in vols.items() if m != n}
                wsum = sum(others.values())
                mesh = spec.mesh_share if wsum > 0 else 0.0
                exchange(n, tc.research_exit_node, ci, v * (1 - mesh), tw)
                for m, w in others.items():
                    exchange(n, m, ci, v * mesh * w / wsum, tw)
            elif spec.pattern == "clients_to_server":
                clients = {m: w for m, w in node_total.items() if m not in (n, exit_node)}
                wsum = sum(clients.values())
                ex = spec.client_exit_share if wsum > 0 else 1.0
                exchange(n, exit_node, ci, v * ex, tw)
                for m, w in clients.items():
                    exchange(n, m, ci, v * (1 - ex) * w / wsum, tw)
    pairs = tuple(sorted(acc))
    gbps = np.array([acc[p] for p in pairs]) if pairs else np.zeros((0, len(names)))
    return ODDemand(pairs, names, gbps)
