from datetime import datetime

import networkx as nx
import pytest

from uetn_twin import engine, topology
from uetn_twin.routing import Router
from uetn_twin.traffic import build_peak_matrix, node_peak_demand


@pytest.fixture(scope="module")
def topo():
    return topology.load()


def _graph(edges):
    g = nx.Graph()
    for i, (a, b, ms) in enumerate(edges):
        g.add_edge(a, b, id=f"l{i}", latency_ms=ms)
    return g


def test_ecmp_splits_equal_cost_paths_evenly():
    g = _graph([("s", "a", 1), ("a", "d", 1), ("s", "b", 1), ("b", "d", 1)])
    fr = Router(g).link_fractions("s", "d")
    assert all(abs(v - 0.5) < 1e-9 for v in fr.values()) and len(fr) == 4


def test_router_prefers_lower_latency_and_reports_unreachable():
    g = _graph([("s", "a", 1), ("a", "d", 1), ("s", "d", 5), ("x", "y", 1)])
    r = Router(g)
    assert set(r.link_fractions("s", "d")) == {"l0", "l1"}
    assert r.link_fractions("s", "x") is None


def test_matrix_conserves_internet_share(topo):
    d = node_peak_demand(topo)
    m = build_peak_matrix(topo)
    exit_node = topo.profile.internet_exit_node
    inet = sum(v for (s, t), v in zip(m.pairs, m.gbps) if t == exit_node)
    assert inet == pytest.approx(topo.profile.internet_share * sum(d.values()))
    inter = m.total_gbps - inet
    assert inter == pytest.approx((1 - topo.profile.internet_share) * sum(d.values()) / 2)


def test_site_total_in_target_range(topo):
    total = sum(g.k12_sites + g.higher_ed_sites + g.healthcare_sites for g in topo.sites)
    assert 2000 <= total <= 2300


def test_simulation_shape_and_diurnal_pattern(topo):
    run = engine.run_simulation(topo, 24)
    assert len(run.snapshots) == 288
    by_time = {s.t: tot for s, tot in zip(run.snapshots, run.total_demand_gbps)}
    assert by_time[datetime(2026, 11, 16, 10)] > 5 * by_time[datetime(2026, 11, 16, 2)]
    assert all(not s.unreachable_nodes for s in run.snapshots)


def test_simulation_is_deterministic(topo):
    a = engine.run_simulation(topo, 1).total_demand_gbps
    b = engine.run_simulation(topo, 1).total_demand_gbps
    assert a == b


def test_link_down_isolates_wendover(topo):
    b = engine.make_backend(topo)
    b.apply_demand(build_peak_matrix(topo))
    b.set_link_state("slc-slcc--wendover", False)
    s = b.observe(datetime(2026, 11, 16, 10))
    assert s.unreachable_nodes == ["wendover"]
    assert s.affected_sites == 8  # 5 K-12 + 3 healthcare, all assumed
    down = next(ls for ls in s.links if ls.link_id == "slc-slcc--wendover")
    assert not down.up and down.load_gbps == 0


def test_spof_has_three_columns(topo):
    df = engine.spof_table(topo)
    assert {"unreachable_nodes", "affected_sites", "overloaded_after_reroute"} <= set(df.columns)
    assert len(df) == len(topo.links)


def test_no_link_above_100_percent_at_normal_peak(topo):
    run = engine.run_simulation(topo, 24)
    worst = max(ls.utilization for s in run.snapshots for ls in s.links)
    assert worst <= 1.0
