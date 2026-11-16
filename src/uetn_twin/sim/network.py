"""Directed flow network: per-direction link load by traffic class, drop at overload, rough queueing latency.

Every link has two directions with the same capacity (full duplex: each direction can carry the full rate at the
same time). Direction 0 is a->b and direction 1 is b->a, as written in links.yaml.

Routing is the v0 shortest-delay ECMP, now keeping the direction of every hop. The routing matrix R has one row
per (link, direction) and one column per OD pair; it is rebuilt only when a link goes up or down, so each tick is
a matrix product: load = R @ demand.

Drop model (approximate): where offered load exceeds capacity, the link's loss ratio is 1 - capacity/load. Each
OD pair loses traffic at the worst loss ratio along its path (its bottleneck), and the dropped amount is attributed
to that bottleneck link. Downstream links are not thinned, so utilization is reported as OFFERED load. This keeps
generated = delivered + dropped exactly, and a link never drops more than its own excess.

Latency is ROUGH AND INDICATIVE ONLY: base x (1 + rho / (1 - rho)), rho = offered utilization capped at 0.99.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import networkx as nx
import numpy as np

from ..backend.flow import FlowBackend
from ..routing import Router
from ..schema import LinkState, Snapshot
from ..topology import Topology, link_latency_ms
from .traffic import ODDemand, TrafficClasses, load_classes

RHO_CAP = 0.99


@dataclass
class FlowResult:
    """Network state for one demand. Arrays are indexed [link, direction(, class)] in topology link order."""

    t: datetime | None
    link_ids: list[str]
    classes: tuple[str, ...]
    load_gbps: np.ndarray        # (L, 2, C) offered load
    utilization: np.ndarray      # (L, 2) offered load / capacity
    dropped_gbps: np.ndarray     # (L, 2, C) dropped traffic attributed to the bottleneck link
    latency_ms: np.ndarray       # (L, 2) rough indicative latency
    node_ids: list[str]
    sessions: np.ndarray         # (N,) concurrent sessions touching each node
    session_capacity: np.ndarray  # (N,)
    generated_gbps: float
    delivered_gbps: float
    dropped_total_gbps: float    # includes unreachable demand
    unreachable_gbps: float
    unreachable_nodes: list[str]

    @property
    def link_utilization(self) -> np.ndarray:
        """(L,) the busier of the two directions, as drawn on the map."""
        return self.utilization.max(axis=1)

    @property
    def session_utilization(self) -> np.ndarray:
        return self.sessions / self.session_capacity


class DirectedFlowBackend(FlowBackend):
    """FlowBackend plus directed, per-class demand. v0's apply_demand/observe keep working unchanged."""

    def load(self, topology: Topology, classes: TrafficClasses | None = None) -> None:
        super().load(topology)
        self.tc = classes or load_classes()
        nodes = topology.node_map()
        self._base_latency = np.array([link_latency_ms(ln, nodes, topology.physics) for ln in self._links])
        self._node_ids = [n.id for n in topology.nodes]
        self._node_idx = {n: i for i, n in enumerate(self._node_ids)}
        caps = self.tc.session_capacity(topology)
        self._session_cap = np.array([caps[n] for n in self._node_ids], dtype=float)
        self._od: ODDemand | None = None
        self._dcache: dict[frozenset[str], tuple] = {}

    def apply_class_demand(self, od: ODDemand) -> None:
        if self._od is None or od.pairs != self._od.pairs:
            self._dcache.clear()
        self._od = od

    def _directed_routing(self):
        key = frozenset(self._down)
        if key not in self._dcache:
            g = self._graph.copy()
            g.remove_edges_from([(ln.a, ln.b) for ln in self._links if ln.id in key])
            router = Router(g)
            pairs = self._od.pairs
            r = np.zeros((2 * len(self._links), len(pairs)))
            ok = np.zeros(len(pairs), dtype=bool)
            ends = np.zeros((len(self._node_ids), len(pairs)))
            for k, (s, d) in enumerate(pairs):
                ends[self._node_idx[s], k] = ends[self._node_idx[d], k] = 1.0
                fr = router.directed_link_fractions(s, d)
                if fr is None:
                    continue
                ok[k] = True
                for (lid, frm), f in fr.items():
                    i = self._idx[lid]
                    r[2 * i + (0 if frm == self._links[i].a else 1), k] = f
            exit_node = self.topo.profile.internet_exit_node
            connected = nx.node_connected_component(g, exit_node) if exit_node in g else set()
            self._dcache[key] = (r, r > 0, ok, ends, connected)
        return self._dcache[key]

    def evaluate(self, t: datetime | None = None) -> FlowResult:
        if self._od is None:
            raise RuntimeError("apply_class_demand() must be called before evaluate()")
        r, used, ok, ends, connected = self._directed_routing()
        od = self._od
        vol = od.gbps * ok[:, None]                       # (P, C), unreachable pairs removed
        unreachable = float(od.gbps[~ok].sum())
        load = r @ vol                                     # (2L, C)
        total = load.sum(axis=1)
        cap = np.repeat(self._capacity, 2)
        loss_ratio = np.where(total > cap, 1.0 - cap / np.maximum(total, 1e-12), 0.0)
        dropped = np.zeros_like(load)
        dropped_pairs = 0.0
        if loss_ratio.any():
            weighted = used * loss_ratio[:, None]          # (2L, P)
            loss = weighted.max(axis=0)
            bottleneck = weighted.argmax(axis=0)
            lost = vol * loss[:, None]
            hit = loss > 0
            np.add.at(dropped, bottleneck[hit], lost[hit])
            dropped_pairs = float(lost.sum())
        util = total / cap
        rho = np.minimum(util, RHO_CAP)
        latency = np.repeat(self._base_latency, 2) * (1 + rho / (1 - rho))
        spg = np.array([self.tc.classes[c].sessions_per_gbps for c in od.classes])
        sessions = ends @ (vol @ spg)
        n_links = len(self._links)
        return FlowResult(
            t=t, link_ids=[ln.id for ln in self._links], classes=od.classes,
            load_gbps=load.reshape(n_links, 2, -1), utilization=util.reshape(n_links, 2),
            dropped_gbps=dropped.reshape(n_links, 2, -1), latency_ms=latency.reshape(n_links, 2),
            node_ids=self._node_ids, sessions=sessions, session_capacity=self._session_cap,
            generated_gbps=od.total_gbps, delivered_gbps=float(vol.sum()) - dropped_pairs,
            dropped_total_gbps=dropped_pairs + unreachable, unreachable_gbps=unreachable,
            unreachable_nodes=sorted(n for n in self._graph.nodes if n not in connected),
        )

    def observe(self, t: datetime) -> Snapshot:
        """v0 Snapshot. With class demand applied, each link reports its busier direction."""
        if self._od is None:
            return super().observe(t)
        res = self.evaluate(t)
        r, used, ok, _, _ = self._directed_routing()
        active = (self._od.gbps.sum(axis=1) * ok) > 0
        flows = (used.reshape(len(self._links), 2, -1).any(axis=1) & active).sum(axis=1)
        busiest = res.utilization.argmax(axis=1)
        links = []
        for i, ln in enumerate(self._links):
            up = ln.id not in self._down
            d = busiest[i]
            links.append(LinkState(link_id=ln.id, up=up, load_gbps=float(res.load_gbps[i, d].sum()) if up else 0.0,
                                   utilization=float(res.utilization[i, d]) if up else 0.0, flows=int(flows[i]) if up else 0))
        return Snapshot(t=t, links=links, unreachable_nodes=res.unreachable_nodes,
                        affected_sites=sum(self._sites.get(n, 0) for n in res.unreachable_nodes))
