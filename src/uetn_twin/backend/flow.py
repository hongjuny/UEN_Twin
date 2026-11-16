"""Flow-level backend: routes aggregate node-pair volumes over shortest paths (ECMP) and sums link load.

"flows" in a LinkState counts the node-pair aggregates with non-zero traffic crossing the link,
not individual TCP flows. Direction is ignored (a pair's volume counts once on each link it crosses).
Internet traffic is mostly downstream, so the summed load approximates real downstream utilization and
overstates upstream (per-direction link modeling is a v1 backlog item).
"""

from __future__ import annotations

from datetime import datetime

import networkx as nx
import numpy as np

from ..routing import Router
from ..schema import LinkState, Snapshot
from ..topology import Topology, to_graph
from ..traffic import DemandMatrix
from .base import NetworkBackend


class FlowBackend(NetworkBackend):
    def load(self, topology: Topology) -> None:
        self.topo = topology
        self._graph = to_graph(topology)
        self._links = list(topology.links)
        self._idx = {ln.id: i for i, ln in enumerate(self._links)}
        self._capacity = np.array([ln.capacity_gbps for ln in self._links])
        self._down: set[str] = set()
        self._demand: DemandMatrix | None = None
        self._cache: dict[frozenset[str], tuple[np.ndarray, np.ndarray, set[str]]] = {}
        self._sites = {}
        for g in topology.sites:
            self._sites[g.parent] = self._sites.get(g.parent, 0) + g.k12_sites + g.higher_ed_sites + g.healthcare_sites

    def set_link_state(self, link_id: str, up: bool) -> None:
        if link_id not in self._idx:
            raise KeyError(f"unknown link: {link_id}")
        (self._down.discard if up else self._down.add)(link_id)

    def apply_demand(self, matrix: DemandMatrix) -> None:
        if self._demand is None or matrix.pairs != self._demand.pairs:
            self._cache.clear()
        self._demand = matrix

    def _routing(self):
        """(routing matrix links x pairs, reachable flag per pair, nodes connected to the exit) for the current down set."""
        key = frozenset(self._down)
        if key not in self._cache:
            g = self._graph.copy()
            g.remove_edges_from([(ln.a, ln.b) for ln in self._links if ln.id in key])
            router = Router(g)
            pairs = self._demand.pairs
            r = np.zeros((len(self._links), len(pairs)))
            ok = np.zeros(len(pairs), dtype=bool)
            for k, (s, d) in enumerate(pairs):
                fr = router.link_fractions(s, d)
                if fr is None:
                    continue
                ok[k] = True
                for lid, f in fr.items():
                    r[self._idx[lid], k] = f
            exit_node = self.topo.profile.internet_exit_node
            connected = nx.node_connected_component(g, exit_node) if exit_node in g else set()
            self._cache[key] = (r, ok, connected)
        return self._cache[key]

    def observe(self, t: datetime) -> Snapshot:
        if self._demand is None:
            raise RuntimeError("apply_demand() must be called before observe()")
        r, ok, connected = self._routing()
        vol = self._demand.gbps * ok
        load = r @ vol
        flows = (r > 0).astype(int) @ (vol > 0).astype(int)
        links = []
        for i, ln in enumerate(self._links):
            up = ln.id not in self._down
            ld = float(load[i]) if up else 0.0
            links.append(LinkState(link_id=ln.id, up=up, load_gbps=ld,
                                   utilization=ld / float(self._capacity[i]), flows=int(flows[i]) if up else 0))
        unreachable = sorted(n for n in self._graph.nodes if n not in connected)
        return Snapshot(t=t, links=links, unreachable_nodes=unreachable,
                        affected_sites=sum(self._sites.get(n, 0) for n in unreachable))
