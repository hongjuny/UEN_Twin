"""Load topology YAML, check consistency, and convert to a networkx graph."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import networkx as nx
import yaml
from pydantic import BaseModel, ValidationError

from .schema import Link, Node, Physics, SiteGroup, TrafficProfile

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "topology"


class Topology(BaseModel):
    nodes: list[Node]
    links: list[Link]
    sites: list[SiteGroup]
    physics: Physics
    profile: TrafficProfile

    def node_map(self) -> dict[str, Node]:
        return {n.id: n for n in self.nodes}


class TopologyError(Exception):
    """Raised with a list of human-readable problems."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def _read(path: Path, key: str) -> list[dict]:
    data = yaml.safe_load(path.read_text()) or {}
    items = data.get(key) or []
    if not isinstance(items, list):
        raise TopologyError([f"{path.name}: '{key}' must be a list"])
    return items


def load(directory: Path = DEFAULT_DIR) -> Topology:
    """Parse the three YAML files. Raises TopologyError listing every schema violation."""
    problems: list[str] = []
    parsed: dict[str, list] = {}
    for fname, key, model in [
        ("nodes.yaml", "nodes", Node),
        ("links.yaml", "links", Link),
        ("sites.yaml", "sites", SiteGroup),
    ]:
        out = []
        for i, raw in enumerate(_read(directory / fname, key)):
            try:
                out.append(model.model_validate(raw))
            except ValidationError as e:
                for err in e.errors():
                    loc = ".".join(str(x) for x in err["loc"])
                    problems.append(f"{fname}[{i}] ({raw.get('id', raw.get('parent', '?'))}): {loc}: {err['msg']}")
        parsed[key] = out
    extra = {}
    for fname, key, model in [("physics.yaml", "physics", Physics), ("traffic_profile.yaml", "profile", TrafficProfile)]:
        try:
            extra[key] = model.model_validate(yaml.safe_load((directory.parent / fname).read_text()))
        except (ValidationError, OSError, yaml.YAMLError) as e:
            problems.append(f"{fname}: {e}")
    if problems:
        raise TopologyError(problems)
    return Topology(**parsed, **extra)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = radians(lat1), radians(lat2)
    h = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))


def link_latency_ms(link: Link, nodes: dict[str, Node], physics: Physics) -> float:
    """Explicit latency if given, else distance-based estimate (confidence stays 'assumed')."""
    if link.latency_ms is not None:
        return link.latency_ms
    a, b = nodes[link.a], nodes[link.b]
    km = haversine_km(a.lat, a.lon, b.lat, b.lon) * physics.detour_factor
    return max(km * physics.fiber_us_per_km / 1000.0, physics.min_latency_ms)


def to_graph(topo: Topology, include_external: bool = False) -> nx.Graph:
    nodes = topo.node_map()
    g = nx.Graph()
    for n in topo.nodes:
        if n.tier == "external" and not include_external:
            continue
        g.add_node(n.id, tier=n.tier)
    for ln in topo.links:
        if ln.a in g and ln.b in g:
            g.add_edge(
                ln.a, ln.b, id=ln.id, capacity_gbps=ln.capacity_gbps,
                latency_ms=link_latency_ms(ln, nodes, topo.physics), link_class=ln.link_class.value,
            )
    return g


def check_consistency(topo: Topology) -> list[str]:
    """Cross-record checks that pydantic alone can't do. Returns problems (empty = OK)."""
    problems: list[str] = []
    node_ids = [n.id for n in topo.nodes]
    node_set = set(node_ids)

    for dup in {i for i in node_ids if node_ids.count(i) > 1}:
        problems.append(f"duplicate node id: {dup}")

    link_ids = [ln.id for ln in topo.links]
    for dup in {i for i in link_ids if link_ids.count(i) > 1}:
        problems.append(f"duplicate link id: {dup}")

    seen_pairs: dict[frozenset[str], str] = {}
    for ln in topo.links:
        for end in (ln.a, ln.b):
            if end not in node_set:
                problems.append(f"link {ln.id}: unknown node '{end}'")
        pair = frozenset((ln.a, ln.b))
        if pair in seen_pairs:
            problems.append(f"link {ln.id}: duplicates {seen_pairs[pair]} ({ln.a}-{ln.b})")
        seen_pairs[pair] = ln.id

    parents = [s.parent for s in topo.sites]
    for p in parents:
        if p not in node_set:
            problems.append(f"sites: unknown parent node '{p}'")
    for dup in {p for p in parents if parents.count(p) > 1}:
        problems.append(f"sites: more than one entry for parent '{dup}'")

    if problems or not topo.nodes:
        return problems

    g = to_graph(topo)
    if g.number_of_nodes() and not nx.is_connected(g):
        comps = sorted(nx.connected_components(g), key=len)
        for c in comps[:-1]:
            problems.append(f"disconnected from main graph: {sorted(c)}")
    exit_node = topo.profile.internet_exit_node
    if exit_node in g:
        reach = nx.node_connected_component(g, exit_node)
        for n in topo.nodes:
            if n.tier == "distribution" and n.id not in reach:
                problems.append(f"distribution node {n.id} has no path to {exit_node}")
    elif g.number_of_nodes():
        problems.append(f"internet exit node '{exit_node}' not found")
    return problems
