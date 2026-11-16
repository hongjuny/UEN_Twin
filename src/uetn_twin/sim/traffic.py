"""Traffic classes and origin-destination (OD) demand by class.

Demand is held as a (class x node) volume matrix V: V[c, n] is the class-c traffic owned by node n (a school's
video, a campus's research transfers, a server's registration requests). A fixed linear map (ODMap) spreads V over
directed OD pairs according to each class's pattern, so a simulation tick is a matrix product, not a Python loop.

An OD pair (src, dst) carries traffic flowing FROM src TO dst. Unlike v0, direction matters: a school's
downstream video and its small upstream share are two different pairs.

Demand at a moment = baseline (site demand x class mix x hourly curve x day-of-week) x regional wander + bursts.
TrafficGenerator below produces it tick by tick from one seeded numpy Generator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import networkx as nx
import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..schema import Confidence
from ..topology import Topology

DEFAULT_CLASSES = Path(__file__).resolve().parents[3] / "data" / "traffic" / "classes.yaml"
SiteType = Literal["k12", "higher_ed", "healthcare"]
Pattern = Literal["exit_to_node", "cache_or_exit_to_node", "exit_and_hospital", "campus_mesh_and_exit", "clients_to_server"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Wander(_Strict):
    """Mean-reverting regional fluctuation (Ornstein-Uhlenbeck process)."""

    tau_minutes: float = Field(gt=0, description="How long a deviation lasts before it fades (time constant)")
    sigma: float = Field(ge=0, lt=1, description="Typical relative size of the fluctuation (0.15 = +/-15%)")


class BurstSchedule(_Strict):
    """Part of the bursts tied to recurring windows around the hour (class changes)."""

    share: float = Field(ge=0, le=1, description="Fraction of all bursts that fall inside the windows")
    first_hour: int = Field(ge=0, le=23)
    last_hour: int = Field(ge=0, le=23)
    minutes_before: float = Field(ge=0, lt=60)
    minutes_after: float = Field(ge=0, lt=60)

    def window_hours(self) -> float:
        return (self.last_hour - self.first_hour + 1) * (self.minutes_before + self.minutes_after) / 60

    def inside(self, t: datetime) -> bool:
        m = t.minute + t.second / 60
        if m >= 60 - self.minutes_before:
            return self.first_hour <= t.hour + 1 <= self.last_hour
        if m < self.minutes_after:
            return self.first_hour <= t.hour <= self.last_hour
        return False


class Bursts(_Strict):
    """Short extra demand: Poisson arrivals, lognormal size relative to the node's class peak."""

    rate_per_hour: float = Field(ge=0, description="Average bursts per node per hour")
    median_fraction: float = Field(ge=0, description="Median burst size as a fraction of the node's class peak")
    sigma_log: float = Field(ge=0, description="Spread of burst sizes (lognormal sigma)")
    min_minutes: float = Field(gt=0)
    max_minutes: float = Field(gt=0)
    schedule: BurstSchedule | None = None

    def rate_at(self, t: datetime) -> float:
        """Arrival rate per second at time t (random part plus scheduled windows, same daily expected count)."""
        per_s = self.rate_per_hour / 3600.0
        if self.schedule is None:
            return per_s
        sch = self.schedule
        rate = per_s * (1 - sch.share)
        if sch.inside(t):
            rate += per_s * sch.share * 24 / sch.window_hours()
        return rate


class FastNoise(_Strict):
    """Per-tick multiplicative AR(1) noise whose size shrinks with the square root of the volume."""

    ar_coefficient: float = Field(ge=0, lt=1)
    sigma_ref: float = Field(ge=0)
    ref_gbps: float = Field(gt=0)
    ref_sessions: float = Field(gt=0)
    min_sigma: float = Field(ge=0)
    max_sigma: float = Field(ge=0, lt=1)


class ClassSpec(_Strict):
    """One traffic class. See the comments in data/traffic/classes.yaml for every field."""

    description: str
    pattern: Pattern
    toward_node_share: float = Field(ge=0, le=1, description="Share flowing toward the node that owns the demand")
    sessions_per_gbps: float = Field(ge=0, description="Concurrent connections per Gbps")
    priority: int = Field(ge=1, le=5, description="1 = highest; used by intervention tools later")
    mesh_share: float = Field(default=0.5, ge=0, le=1)
    client_exit_share: float = Field(default=0.5, ge=0, le=1)
    floor: float = Field(default=0.0, ge=0, le=1, description="Lowest hourly level (fraction of peak)")
    wander: Wander
    bursts: Bursts
    hourly: dict[str, list[float]]

    @model_validator(mode="after")
    def _check_hours(self) -> ClassSpec:
        for mode, vals in self.hourly.items():
            if len(vals) != 24:
                raise ValueError(f"hourly.{mode} needs 24 values, got {len(vals)}")
        return self


class TrafficClasses(_Strict):
    """Contents of data/traffic/classes.yaml. Everything is assumed."""

    confidence: Confidence
    research_exit_node: str
    cdn_cache_nodes: list[str]
    cdn_share: float = Field(ge=0, le=1)
    hospital_nodes: list[str]
    regional_correlation: float = Field(ge=0, le=1, description="How strongly nodes of one region move together")
    fast_noise: FastNoise
    day_of_week_factor: list[float] = Field(min_length=7, max_length=7, description="Monday..Sunday multipliers")
    server_session_class: str = Field(description="Class whose sessions load the server side (registration, logins)")
    tracked_session_classes: list[str] = Field(default_factory=list, description="Sessions recorded, not capacity-checked")
    site_mix: dict[SiteType, dict[str, float]]
    session_capacity_by_kind: dict[str, int]
    session_capacity_by_node: dict[str, int] = Field(default_factory=dict)
    classes: dict[str, ClassSpec]

    @model_validator(mode="after")
    def _check(self) -> TrafficClasses:
        for site, mix in self.site_mix.items():
            unknown = set(mix) - set(self.classes)
            if unknown:
                raise ValueError(f"site_mix.{site}: unknown classes {sorted(unknown)}")
            if abs(sum(mix.values()) - 1.0) > 1e-9:
                raise ValueError(f"site_mix.{site} must sum to 1, got {sum(mix.values())}")
        for c in [self.server_session_class, *self.tracked_session_classes]:
            if c not in self.classes:
                raise ValueError(f"unknown session class {c}")
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
    """class -> node -> deterministic volume at time t under an academic mode (weekday_semester / weekend / break)."""
    peaks = class_peaks(topo, tc)
    dow = tc.day_of_week_factor[t.weekday()]
    return {name: {n: v * dow * class_level(tc.classes[name], mode, t) for n, v in peaks[name].items()}
            for name in tc.names}


def class_level(spec: ClassSpec, mode: str, t: datetime) -> float:
    return max(curve_value(spec.hourly[mode], t), spec.floor)


@dataclass(frozen=True)
class ODDemand:
    """Directed demand: gbps[p, c] is class c traffic flowing from pairs[p][0] to pairs[p][1].

    node_volumes[c, n] is the owned volume that produced it (used for server-side session counts)."""

    pairs: tuple[tuple[str, str], ...]
    classes: tuple[str, ...]
    gbps: np.ndarray
    node_ids: tuple[str, ...] = ()
    node_volumes: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))

    @property
    def total_gbps(self) -> float:
        return float(self.gbps.sum())

    def only(self, *names: str) -> ODDemand:
        keep = np.array([c in names for c in self.classes], dtype=float)
        nv = self.node_volumes * keep[:, None] if self.node_volumes.size else self.node_volumes
        return ODDemand(self.pairs, self.classes, self.gbps * keep, self.node_ids, nv)

    def scaled(self, factor: float) -> ODDemand:
        return ODDemand(self.pairs, self.classes, self.gbps * factor, self.node_ids, self.node_volumes * factor)


class ODMap:
    """Fixed linear map from owned volumes V (class x node) to directed OD demand (pair x class)."""

    def __init__(self, topo: Topology, tc: TrafficClasses):
        self.classes = tc.names
        self.node_ids = tuple(n.id for n in topo.nodes)
        self.node_idx = {n: i for i, n in enumerate(self.node_ids)}
        exit_node = topo.profile.internet_exit_node
        peaks = class_peaks(topo, tc)
        node_total: dict[str, float] = {}
        for vols in peaks.values():
            for n, v in vols.items():
                node_total[n] = node_total.get(n, 0.0) + v
        coef: dict[tuple[int, tuple[str, str], int], float] = {}

        def add(ci: int, src: str, dst: str, n: int, w: float) -> None:
            if src != dst and w > 0:  # traffic that stays inside one node never crosses a link
                key = (ci, (src, dst), n)
                coef[key] = coef.get(key, 0.0) + w

        def exchange(ci: int, owner: str, other: str, w: float, toward: float) -> None:
            n = self.node_idx[owner]
            add(ci, other, owner, n, w * toward)
            add(ci, owner, other, n, w * (1 - toward))

        # Weights use the peak volumes (fixed), so the map stays linear while volumes fluctuate.
        for ci, name in enumerate(self.classes):
            spec = tc.classes[name]
            owners = {n: v for n, v in peaks[name].items() if v > 0}
            tw = spec.toward_node_share
            for n in owners:
                if spec.pattern == "exit_to_node":
                    exchange(ci, n, exit_node, 1.0, tw)
                elif spec.pattern == "cache_or_exit_to_node":
                    caches = tc.cdn_cache_nodes
                    for cache in caches:
                        exchange(ci, n, cache, tc.cdn_share / len(caches), tw)
                    exchange(ci, n, exit_node, 1 - tc.cdn_share if caches else 1.0, tw)
                elif spec.pattern == "exit_and_hospital":
                    hubs = [h for h in tc.hospital_nodes if h != n]
                    hub_part = 0.5 if hubs else 0.0
                    exchange(ci, n, exit_node, 1 - hub_part, tw)
                    for h in hubs:
                        exchange(ci, n, h, hub_part / len(hubs), tw)
                elif spec.pattern == "campus_mesh_and_exit":
                    others = {m: w for m, w in owners.items() if m != n}
                    wsum = sum(others.values())
                    mesh = spec.mesh_share if wsum > 0 else 0.0
                    exchange(ci, n, tc.research_exit_node, 1 - mesh, tw)
                    for m, w in others.items():
                        exchange(ci, n, m, mesh * w / wsum, tw)
                elif spec.pattern == "clients_to_server":
                    clients = {m: w for m, w in node_total.items() if m not in (n, exit_node)}
                    wsum = sum(clients.values())
                    ex = spec.client_exit_share if wsum > 0 else 1.0
                    exchange(ci, n, exit_node, ex, tw)
                    for m, w in clients.items():
                        exchange(ci, n, m, (1 - ex) * w / wsum, tw)
        self.pairs = tuple(sorted({p for _, p, _ in coef}))
        pidx = {p: i for i, p in enumerate(self.pairs)}
        self.matrix = np.zeros((len(self.classes), len(self.pairs), len(self.node_ids)))
        for (ci, p, n), w in coef.items():
            self.matrix[ci, pidx[p], n] = w

    def add_pairs(self, pairs) -> None:
        """Make room for extra OD pairs (e.g. scenario overlays) with zero baseline weight."""
        have = set(self.pairs)
        new = sorted(p for p in pairs if p not in have)
        if not new:
            return
        for a, b in new:
            if a not in self.node_idx or b not in self.node_idx:
                raise ValueError(f"unknown node in pair {(a, b)}")
        self.pairs = self.pairs + tuple(new)
        pad = np.zeros((len(self.classes), len(new), len(self.node_ids)))
        self.matrix = np.concatenate([self.matrix, pad], axis=1)

    def volumes_array(self, volumes: dict[str, dict[str, float]]) -> np.ndarray:
        v = np.zeros((len(self.classes), len(self.node_ids)))
        for ci, name in enumerate(self.classes):
            for n, x in volumes.get(name, {}).items():
                v[ci, self.node_idx[n]] = x
        return v

    def demand(self, v: np.ndarray) -> ODDemand:
        gbps = np.einsum("cpn,cn->pc", self.matrix, v)
        return ODDemand(self.pairs, self.classes, gbps, self.node_ids, v)


def build_od(topo: Topology, tc: TrafficClasses, volumes: dict[str, dict[str, float]]) -> ODDemand:
    """Convenience: OD demand for one volume dict (builds the map each call; use ODMap in loops)."""
    m = ODMap(topo, tc)
    return m.demand(m.volumes_array(volumes))


def regions(topo: Topology) -> dict[str, str]:
    """node -> region id: a core node is its own region; a distribution node joins the nearest core node (by hops)."""
    g = nx.Graph()
    g.add_nodes_from(n.id for n in topo.nodes)
    g.add_edges_from((ln.a, ln.b) for ln in topo.links)
    tier = {n.id: n.tier for n in topo.nodes}
    out = {}
    for n in topo.nodes:
        if n.tier == "core":
            out[n.id] = n.id
            continue
        dist = nx.single_source_shortest_path_length(g, n.id)
        cores = sorted((d, m) for m, d in dist.items() if tier[m] == "core")
        out[n.id] = cores[0][1] if cores else n.id
    return out


class TrafficGenerator:
    """Stochastic owned volumes V[class, node] over time.

    1. baseline: class peak x day-of-week x hourly curve of the academic mode
    2. wander: exp(sigma * x - sigma^2 / 2) with x a unit-variance Ornstein-Uhlenbeck mix of a regional factor
       (shared by a core PoP and its distribution nodes) and a node factor; corr(regional) = regional_correlation
    3. bursts: Poisson arrivals per (class, node); size = lognormal x class peak x current hourly level; flat for a
       uniform 1-10 min duration; part of a class's bursts can be tied to recurring windows (class changes)
    4. fast noise: multiplicative AR(1) per (class, node) every tick, sigma = sigma_ref x sqrt(ref / volume)
       (Gbps, or sessions for the server-session class), clipped; aggregation then makes big links smooth and
       small links jittery, as in real telemetry

    Every draw comes from one numpy Generator, so the same seed reproduces the same traffic.
    """

    def __init__(self, topo: Topology, tc: TrafficClasses, odmap: ODMap, mode: str, rng: np.random.Generator):
        self.tc, self.mode, self.rng = tc, mode, rng
        self.classes = odmap.classes
        self.peaks = odmap.volumes_array(class_peaks(topo, tc))          # (C, N)
        reg = regions(topo)
        names = sorted(set(reg.values()))
        self.region_idx = np.array([names.index(reg[n]) for n in odmap.node_ids])
        c, n = self.peaks.shape
        self.tau_s = np.array([tc.classes[k].wander.tau_minutes * 60 for k in self.classes])
        self.sigma = np.array([tc.classes[k].wander.sigma for k in self.classes])
        self.rho = tc.regional_correlation
        self.z_region = rng.standard_normal((c, len(names)))
        self.z_node = rng.standard_normal((c, n))
        b = [tc.classes[k].bursts for k in self.classes]
        self.burst_median = np.array([x.median_fraction for x in b])
        self.burst_sigma = np.array([x.sigma_log for x in b])
        self.burst_min = np.array([x.min_minutes for x in b]) * 60
        self.burst_max = np.array([x.max_minutes for x in b]) * 60
        self.burst_specs = b
        self._bursts = np.zeros((0, 4))  # rows: end_s, class, node, gbps
        self.active = self.peaks > 0
        fn = tc.fast_noise
        self.noise = fn
        self.noise_u = rng.standard_normal((c, n))
        server = self.classes.index(tc.server_session_class)
        self.noise_ref = np.full(c, fn.ref_gbps)
        self.noise_ref[server] = fn.ref_sessions
        self.noise_scale = np.ones(c)  # volume -> reference unit (Gbps or sessions)
        self.noise_scale[server] = tc.classes[tc.server_session_class].sessions_per_gbps

    def level(self, t: datetime) -> np.ndarray:
        """(C,) hourly curve x day-of-week at t."""
        dow = self.tc.day_of_week_factor[t.weekday()]
        return np.array([dow * class_level(self.tc.classes[k], self.mode, t) for k in self.classes])

    def baseline(self, t: datetime) -> np.ndarray:
        return self.peaks * self.level(t)[:, None]

    def step(self, t: datetime, now_s: float, dt_s: float) -> tuple[np.ndarray, np.ndarray]:
        """Advance by dt_s and return (V, burst part of V), both (C, N) in Gbps."""
        a = np.exp(-dt_s / self.tau_s)[:, None]
        k = np.sqrt(1 - a * a)
        self.z_region = a * self.z_region + k * self.rng.standard_normal(self.z_region.shape)
        self.z_node = a * self.z_node + k * self.rng.standard_normal(self.z_node.shape)
        x = np.sqrt(self.rho) * self.z_region[:, self.region_idx] + np.sqrt(1 - self.rho) * self.z_node
        sig = self.sigma[:, None]
        wander = np.exp(sig * x - sig * sig / 2)
        level = self.level(t)
        base = self.peaks * level[:, None]

        rates = np.array([bs.rate_at(t) for bs in self.burst_specs])
        arrivals = self.rng.poisson(rates[:, None] * dt_s * self.active)
        ci, ni = np.nonzero(arrivals)
        if len(ci):
            reps = arrivals[ci, ni]
            ci, ni = np.repeat(ci, reps), np.repeat(ni, reps)
            size = (self.burst_median[ci] * np.exp(self.burst_sigma[ci] * self.rng.standard_normal(len(ci)))
                    * self.peaks[ci, ni] * level[ci])
            dur = self.rng.uniform(self.burst_min[ci], self.burst_max[ci])
            self._bursts = np.vstack([self._bursts, np.column_stack([now_s + dur, ci, ni, size])])
        self._bursts = self._bursts[self._bursts[:, 0] > now_s]
        burst = np.zeros_like(base)
        if len(self._bursts):
            np.add.at(burst, (self._bursts[:, 1].astype(int), self._bursts[:, 2].astype(int)), self._bursts[:, 3])
        v = base * wander + burst
        fn = self.noise
        phi = fn.ar_coefficient
        self.noise_u = phi * self.noise_u + np.sqrt(1 - phi * phi) * self.rng.standard_normal(self.noise_u.shape)
        amount = np.maximum(v * self.noise_scale[:, None], 1e-12)
        sigma = np.clip(fn.sigma_ref * np.sqrt(self.noise_ref[:, None] / amount), fn.min_sigma, fn.max_sigma)
        v = v * np.maximum(1 + sigma * self.noise_u, 0)
        return v, burst
