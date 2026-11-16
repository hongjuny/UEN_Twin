"""Pydantic models for topology data and state snapshots.

Field names and docstrings are written to be readable by people and, later, by
LLM agents that receive a ``Snapshot`` as JSON.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# How a value was obtained:
#   map      - read directly from the UEN|UTN infrastructure map
#   inferred - reasonable deduction from the map (e.g. which PoP a school district attaches to)
#   assumed  - not on the map; we made it up (e.g. latency, number of schools)
Confidence = Literal["map", "inferred", "assumed"]


class LinkClass(StrEnum):
    """Link grade, taken from the map legend. Value is the default capacity in Gbps (see CLASS_CAPACITY_GBPS)."""

    BACKBONE_400G = "backbone_400g"
    BACKBONE_100G = "backbone_100g"
    BACKBONE_40G = "backbone_40g"
    BACKBONE_20G = "backbone_20g"
    ETHERNET_10G = "ethernet_10g"
    ETHERNET_1G = "ethernet_1g"
    MICROWAVE_200M = "microwave_200m"
    ETHERNET_SUB1G = "ethernet_sub1g"


# Gbps = gigabits per second (link speed). "sub1g" is 10-100 Mbps; 0.1 is the upper end.
CLASS_CAPACITY_GBPS: dict[LinkClass, float] = {
    LinkClass.BACKBONE_400G: 400.0,
    LinkClass.BACKBONE_100G: 100.0,
    LinkClass.BACKBONE_40G: 40.0,
    LinkClass.BACKBONE_20G: 20.0,
    LinkClass.ETHERNET_10G: 10.0,
    LinkClass.ETHERNET_1G: 1.0,
    LinkClass.MICROWAVE_200M: 0.2,
    LinkClass.ETHERNET_SUB1G: 0.1,
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Physics(_Strict):
    """Constants for estimating link latency from distance. All values are assumed (data/physics.yaml)."""

    fiber_us_per_km: float = Field(gt=0, description="Propagation delay in fiber, microseconds per km")
    detour_factor: float = Field(ge=1, description="Cable route length / straight-line distance")
    min_latency_ms: float = Field(ge=0, description="Lower bound on any derived link latency")


class Node(_Strict):
    """A router site. ``core`` = backbone PoP (point of presence), ``distribution`` = regional aggregation point."""

    id: str
    name: str = Field(description="Label exactly as printed on the map")
    tier: Literal["core", "distribution", "external"]
    city: str
    lat: float = Field(ge=-90, le=90, description="City-center latitude (assumed)")
    lon: float = Field(ge=-180, le=180, description="City-center longitude (assumed)")
    kind: Literal[
        "pop", "datacenter", "university", "technical_college",
        "school_district", "healthcare", "other",
    ]
    confidence: Confidence
    notes: str = ""


class Link(_Strict):
    """An undirected connection between two nodes."""

    id: str
    a: str = Field(description="Node.id of one endpoint")
    b: str = Field(description="Node.id of the other endpoint")
    link_class: LinkClass
    capacity_gbps: float | None = Field(
        default=None, gt=0, description="Defaults to the class capacity; set to override"
    )
    latency_ms: float | None = Field(
        default=None, ge=0, description="One-way delay; None means derive from geographic distance"
    )
    confidence: Confidence
    notes: str = ""

    @model_validator(mode="after")
    def _fill_capacity(self) -> Link:
        if self.capacity_gbps is None:
            self.capacity_gbps = CLASS_CAPACITY_GBPS[self.link_class]
        if self.a == self.b:
            raise ValueError(f"link {self.id}: endpoints must differ")
        return self


class SiteGroup(_Strict):
    """Access-layer aggregate: schools/hospitals behind one node (not modeled as routers).

    Peak demand is not stored here; it is computed from site counts and the unit demand and
    concurrency factors in data/traffic_profile.yaml (see traffic.group_peak_demand_gbps).
    """

    parent: str = Field(description="Node.id (distribution or core) these sites hang off")
    k12_sites: int = Field(ge=0)
    higher_ed_sites: int = Field(ge=0)
    healthcare_sites: int = Field(ge=0)
    confidence: Confidence


class UnitDemand(_Strict):
    """Demand of one site at its busiest moment if all its users were active, in Gbps."""

    k12_gbps_per_site: float = Field(gt=0)
    healthcare_gbps_per_site: float = Field(gt=0)
    higher_ed_gbps_per_campus: float = Field(gt=0, description="Default; per-node overrides below")


class Concurrency(_Strict):
    """Fraction of unit demand that is actually active at the same time at the daily peak (0-1)."""

    k12: float = Field(ge=0, le=1)
    healthcare: float = Field(ge=0, le=1)
    higher_ed: float = Field(ge=0, le=1)


class TrafficProfile(_Strict):
    """Demand model parameters (data/traffic_profile.yaml). Everything here is assumed."""

    confidence: Confidence
    internet_exit_node: str = Field(description="Node.id where traffic to/from the internet enters the network")
    internet_share: float = Field(ge=0, le=1, description="Share of each node's demand exchanged with the internet exit")
    unit_demand_gbps: UnitDemand
    higher_ed_campus_gbps_by_node: dict[str, float] = Field(default_factory=dict)
    concurrency: Concurrency
    step_minutes: int = Field(gt=0)
    noise_pct: float = Field(ge=0, lt=1, description="Random +/- variation per flow per step")
    seed: int
    hourly_factor: dict[str, list[float]] = Field(
        description="Profile name -> 24 multipliers (hour 0..23) applied to peak demand"
    )

    @model_validator(mode="after")
    def _check_hours(self) -> TrafficProfile:
        for name, vals in self.hourly_factor.items():
            if len(vals) != 24:
                raise ValueError(f"hourly_factor.{name} needs 24 values, got {len(vals)}")
        return self


class LinkState(_Strict):
    """One link at one instant."""

    link_id: str
    up: bool
    load_gbps: float
    utilization: float = Field(description="load / capacity; 1.0 = full, may exceed 1.0 when oversubscribed")
    flows: int = Field(description="Number of traffic flows crossing this link")


class Snapshot(_Strict):
    """Network state at time ``t``."""

    t: datetime
    links: list[LinkState]
    unreachable_nodes: list[str] = Field(description="Nodes with no path to the internet exit")
    affected_sites: int = Field(description="Schools and hospitals behind unreachable nodes")
