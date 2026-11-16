"""Scenarios (data/scenarios/*.yaml): base profile + start time + overlays + events.

A scenario lays a situation over a normal day. Overlays change one traffic class for selected nodes:

  shape types
    spike       {at, rise_min, peak_x, decay_min}       factor rises linearly to peak_x, then decays exponentially
    plateau     {start, end, gbps | factor, ramp_min}    holds an absolute Gbps or a factor, with linear ramps
    ramp        {start, end, to_gbps | to_x}             grows linearly from start to end, then holds
    multiplier  {start, end, factor, ramp_min}           plateau with a factor (multiplies the baseline)
  selectors (targets, sources): node ids, region:<name> (data/regions.yaml), tier:<tier>, kind:<kind>
  od: [from, to]   a one-way flow between two nodes (e.g. an elephant research transfer)
  affects: [gbps, sessions]   for the server-session class, whether the overlay adds traffic, sessions or both

Events (set_link_state) take a link down or up at a time of day; routes are recomputed.
Every size value in a scenario is an assumption chosen for demonstration.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..schema import Confidence
from ..topology import Topology
from .clock import DAYS, SimClock
from .traffic import ODMap, TrafficClasses, class_peaks, regions as nearest_core

ROOT = Path(__file__).resolve().parents[3]
SCENARIO_DIR = ROOT / "data" / "scenarios"
REGIONS_FILE = ROOT / "data" / "regions.yaml"
HHMM = r"^\d{2}:\d{2}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Shape(_Strict):
    type: Literal["spike", "plateau", "ramp", "multiplier"]
    at: str | None = Field(default=None, pattern=HHMM)
    rise_min: float = Field(default=0, ge=0)
    peak_x: float | None = Field(default=None, gt=0)
    decay_min: float = Field(default=30, gt=0)
    start: str | None = Field(default=None, pattern=HHMM)
    end: str | None = Field(default=None, pattern=HHMM)
    gbps: float | None = Field(default=None, ge=0)
    factor: float | None = Field(default=None, ge=0)
    ramp_min: float = Field(default=0, ge=0)
    to_gbps: float | None = Field(default=None, ge=0)
    to_x: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check(self) -> Shape:
        need = {"spike": ("at", "peak_x"), "plateau": ("start", "end"), "ramp": ("start", "end"),
                "multiplier": ("start", "end", "factor")}[self.type]
        missing = [k for k in need if getattr(self, k) is None]
        if missing:
            raise ValueError(f"{self.type} shape needs {missing}")
        if self.type == "plateau" and (self.gbps is None) == (self.factor is None):
            raise ValueError("plateau needs exactly one of gbps or factor")
        if self.type == "ramp" and (self.to_gbps is None) == (self.to_x is None):
            raise ValueError("ramp needs exactly one of to_gbps or to_x")
        return self

    @property
    def absolute(self) -> bool:
        return self.gbps is not None or self.to_gbps is not None

    def compile(self, clock: SimClock) -> tuple[Callable[[float], float], float, float]:
        """(value(sim_s), active_from_s, active_until_s). The value is Gbps for absolute shapes, else a factor."""
        if self.type == "spike":
            a, r, d, px = clock.seconds_until(self.at), self.rise_min * 60, self.decay_min * 60, self.peak_x

            def spike(s: float) -> float:
                if s < a:
                    return 1.0
                if s < a + r:
                    return 1 + (px - 1) * (s - a) / r
                return 1 + (px - 1) * math.exp(-(s - a - r) / d)

            return spike, a, a + r + 5 * d
        st, en, rp = clock.seconds_until(self.start), clock.seconds_until(self.end), self.ramp_min * 60
        if en <= st:
            en += 24 * 3600  # an end of 00:00 means midnight after the start

        def level(s: float) -> float:
            if self.type == "ramp":
                return 0.0 if s < st else min((s - st) / max(en - st, 1), 1.0)
            if s < st or s > en + rp:
                return 0.0
            if rp and s < st + rp:
                return (s - st) / rp
            if s > en:
                return 1 - (s - en) / rp if rp else 0.0
            return 1.0

        until = float("inf") if self.type == "ramp" else en + rp
        if self.absolute:
            top = self.gbps if self.gbps is not None else self.to_gbps
            return (lambda s: top * level(s)), st, until
        top = self.factor if self.factor is not None else self.to_x
        return (lambda s: 1 + (top - 1) * level(s)), st, until


class Overlay(_Strict):
    cls: str = Field(alias="class")
    label: str = ""
    targets: str | list[str] | None = None
    sources: str | list[str] | None = None
    od: list[str] | None = Field(default=None, min_length=2, max_length=2)
    shape: Shape
    affects: list[Literal["gbps", "sessions"]] = Field(default_factory=lambda: ["gbps", "sessions"])

    @model_validator(mode="after")
    def _check(self) -> Overlay:
        if (self.od is None) == (self.targets is None):
            raise ValueError("an overlay needs either targets or od")
        if self.od and not self.shape.absolute:
            raise ValueError("an od overlay needs an absolute size (gbps / to_gbps)")
        return self


class Event(_Strict):
    at: str = Field(pattern=HHMM)
    action: Literal["set_link_state"]
    link: str
    up: bool


class Scenario(_Strict):
    """A situation laid over a normal day. Every size value is an assumption for demonstration."""

    id: str
    title: str
    description: str = ""
    notes: str = ""
    base_profile: Literal["weekday_semester", "weekend", "break"]
    day: Literal[DAYS] = "Monday"  # type: ignore[valid-type]
    start: str = Field(default="00:00", pattern=HHMM)
    duration_hours: float = Field(gt=0)
    seed: int = 42
    confidence: Confidence
    overlays: list[Overlay] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)


def load_scenario(name_or_path: str | Path) -> Scenario:
    """A scenario id from data/scenarios/ or a path to a YAML file."""
    p = Path(name_or_path)
    if not p.suffix:
        p = SCENARIO_DIR / f"{name_or_path}.yaml"
    if not p.exists():
        known = sorted(x.stem for x in SCENARIO_DIR.glob("*.yaml"))
        raise FileNotFoundError(f"scenario '{name_or_path}' not found; known: {known}")
    return Scenario.model_validate(yaml.safe_load(p.read_text()))


def list_scenarios() -> list[str]:
    return sorted(x.stem for x in SCENARIO_DIR.glob("*.yaml"))


def node_regions(topo: Topology, path: Path = REGIONS_FILE) -> dict[str, str]:
    """node -> region name (core nodes as listed; distribution nodes via their nearest core node)."""
    spec = yaml.safe_load(Path(path).read_text())["regions"]
    core_region = {c: r for r, cores in spec.items() for c in cores}
    return {n: core_region.get(core) for n, core in nearest_core(topo).items() if core_region.get(core)}


def resolve(selector: str | list[str], topo: Topology, region_of: dict[str, str]) -> list[str]:
    items = [selector] if isinstance(selector, str) else selector
    nodes = topo.node_map()
    out: list[str] = []
    for item in items:
        if item.startswith("region:"):
            found = [n for n, r in region_of.items() if r == item[7:]]
        elif item.startswith("tier:"):
            found = [n.id for n in topo.nodes if n.tier == item[5:]]
        elif item.startswith("kind:"):
            found = [n.id for n in topo.nodes if n.kind == item[5:]]
        else:
            found = [item] if item in nodes else []
        if not found:
            raise ValueError(f"selector '{item}' matches no node")
        out += [n for n in found if n not in out]
    return out


def find_link(topo: Topology, name: str) -> str:
    """Link id for 'a--b' in either orientation."""
    a, _, b = name.partition("--")
    for ln in topo.links:
        if {ln.a, ln.b} == {a, b}:
            return ln.id
    raise ValueError(f"unknown link {name}")


class CompiledOverlay:
    """An overlay turned into per-tick extra owned volume at its owner nodes plus a pair-distribution matrix."""

    def __init__(self, ov: Overlay, topo: Topology, tc: TrafficClasses, odmap: ODMap, clock: SimClock,
                 region_of: dict[str, str]):
        if ov.cls not in tc.classes:
            raise ValueError(f"unknown class {ov.cls}")
        self.ov, self.ci = ov, odmap.classes.index(ov.cls)
        spec = tc.classes[ov.cls]
        exit_node = topo.profile.internet_exit_node
        if ov.od:
            for n in ov.od:
                resolve(n, topo, region_of)
            self.owners = [ov.od[0]]
            self.weights: list[dict[tuple[str, str], float] | None] = [{(ov.od[0], ov.od[1]): 1.0}]
        else:
            self.owners = resolve(ov.targets, topo, region_of)
            self.weights = []
            if ov.sources is None:
                self.weights = [None] * len(self.owners)  # use the class's normal pattern
            else:
                srcs = resolve(ov.sources, topo, region_of)
                totals: dict[str, float] = {}
                for vols in class_peaks(topo, tc).values():
                    for n, v in vols.items():
                        totals[n] = totals.get(n, 0.0) + v
                ex = spec.client_exit_share if spec.pattern == "clients_to_server" else 0.0
                tw = spec.toward_node_share
                for owner in self.owners:
                    others = {s: totals.get(s, 0.0) for s in srcs if s != owner and totals.get(s, 0.0) > 0}
                    wsum = sum(others.values())
                    e = ex if wsum > 0 else 1.0
                    w: dict[tuple[str, str], float] = {}
                    for other, share in [(exit_node, e)] + [(s, (1 - e) * x / wsum) for s, x in others.items()]:
                        if other != owner and share > 0:
                            w[(other, owner)] = w.get((other, owner), 0.0) + share * tw
                            w[(owner, other)] = w.get((owner, other), 0.0) + share * (1 - tw)
                    self.weights.append(w)
        self.owner_idx = np.array([odmap.node_idx[n] for n in self.owners])
        self.value, self.active_from, self.active_until = ov.shape.compile(clock)
        self.absolute = ov.shape.absolute
        self.add_gbps = "gbps" in ov.affects
        self.add_volume = "sessions" in ov.affects or ov.cls != tc.server_session_class
        self.D: np.ndarray | None = None

    def needed_pairs(self) -> set[tuple[str, str]]:
        return {p for w in self.weights if w for p in w}

    def finalize(self, odmap: ODMap) -> None:
        """Build the (pairs x owners) distribution matrix once the ODMap holds every needed pair."""
        pidx = {p: i for i, p in enumerate(odmap.pairs)}
        self.D = np.zeros((len(odmap.pairs), len(self.owners)))
        for k, (owner, w) in enumerate(zip(self.owners, self.weights)):
            if w is None:
                self.D[:, k] = odmap.matrix[self.ci][:, odmap.node_idx[owner]]
            else:
                for p, x in w.items():
                    self.D[pidx[p], k] = x

    def extra(self, sim_s: float, v: np.ndarray) -> np.ndarray:
        """(owners,) extra owned Gbps at sim_s, given the current volumes v (class x node)."""
        if not (self.active_from <= sim_s <= self.active_until):
            return np.zeros(len(self.owners))
        x = self.value(sim_s)
        if self.absolute:
            return np.full(len(self.owners), x / len(self.owners))
        return (x - 1.0) * v[self.ci, self.owner_idx]
