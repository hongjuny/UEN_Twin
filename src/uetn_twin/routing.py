"""Shortest-path routing with ECMP.

ECMP (Equal-Cost Multi-Path): when several paths have the same total delay, traffic is split
equally among them. Edge weight is delay in whole microseconds so that ties are exact.
"""

from __future__ import annotations

import networkx as nx


class Router:
    """Routes over a fixed graph (build a new Router when a link goes up or down)."""

    def __init__(self, graph: nx.Graph):
        self.g = graph
        self._trees: dict[str, tuple[dict, dict, dict]] = {}

    def _tree(self, src: str):
        if src not in self._trees:
            pred, dist = nx.dijkstra_predecessor_and_distance(
                self.g, src, weight=lambda u, v, d: max(1, round(d["latency_ms"] * 1000))
            )
            count: dict[str, int] = {}
            for v in sorted(dist, key=dist.get):
                count[v] = 1 if v == src else sum(count[p] for p in pred[v])
            self._trees[src] = (pred, dist, count)
        return self._trees[src]

    def reachable(self, src: str, dst: str) -> bool:
        return src in self.g and dst in self.g and dst in self._tree(src)[1]

    def link_fractions(self, src: str, dst: str) -> dict[str, float] | None:
        """Fraction of the src->dst traffic carried by each link id (equal split over equal-cost paths).
        None if dst is unreachable."""
        directed = self.directed_link_fractions(src, dst)
        if directed is None:
            return None
        out: dict[str, float] = {}
        for (lid, _), share in directed.items():
            out[lid] = out.get(lid, 0.0) + share
        return out

    def directed_link_fractions(self, src: str, dst: str) -> dict[tuple[str, str], float] | None:
        """Like link_fractions, keyed by (link id, node the traffic leaves from) so the direction is known."""
        if not self.reachable(src, dst):
            return None
        pred, dist, count = self._tree(src)
        flow = {dst: 1.0}
        out: dict[tuple[str, str], float] = {}
        for v in sorted(dist, key=dist.get, reverse=True):
            f = flow.get(v)
            if not f or v == src:
                continue
            for p in pred[v]:
                share = f * count[p] / count[v]
                key = (self.g[p][v]["id"], p)
                out[key] = out.get(key, 0.0) + share
                flow[p] = flow.get(p, 0.0) + share
        return out
