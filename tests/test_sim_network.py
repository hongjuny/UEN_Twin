from datetime import datetime
import time

import networkx as nx
import numpy as np
import pytest

from uetn_twin import topology
from uetn_twin.routing import Router
from uetn_twin.sim.network import DirectedFlowBackend
from uetn_twin.sim.traffic import baseline_volumes, build_od, load_classes
from uetn_twin.traffic import build_peak_matrix

T10 = datetime(2026, 11, 16, 10, 0)


@pytest.fixture(scope="module")
def topo():
    return topology.load()


@pytest.fixture(scope="module")
def tc():
    return load_classes()


@pytest.fixture()
def backend(topo, tc):
    b = DirectedFlowBackend()
    b.load(topo, tc)
    return b


def _od(topo, tc, mode="weekday_semester", t=T10):
    return build_od(topo, tc, baseline_volumes(topo, tc, mode, t))


def _dir_load(res, link_id, frm):
    i = res.link_ids.index(link_id)
    a = link_id.split("--")[0]
    return res.load_gbps[i, 0 if frm == a else 1].sum()


def test_classes_config(tc):
    assert set(tc.names) == {"k12_instruction", "general_internet", "streaming", "telehealth", "research_bulk", "transactional"}
    assert tc.confidence == "assumed"
    for mix in tc.site_mix.values():
        assert sum(mix.values()) == pytest.approx(1.0)


def test_directed_fractions_follow_the_path():
    g = nx.Graph()
    g.add_edge("s", "m", id="l0", latency_ms=1)
    g.add_edge("m", "d", id="l1", latency_ms=1)
    fr = Router(g).directed_link_fractions("s", "d")
    assert fr == {("l0", "s"): 1.0, ("l1", "m"): 1.0}
    assert set(Router(g).directed_link_fractions("d", "s")) == {("l0", "m"), ("l1", "d")}


def test_baseline_total_close_to_v0(topo, tc):
    v0_total = build_peak_matrix(topo).total_gbps  # v0 matrix at the weekday peak
    assert _od(topo, tc).total_gbps == pytest.approx(v0_total, rel=0.15)


def test_conservation_without_and_with_overload(topo, tc, backend):
    od = _od(topo, tc)
    for scale in (1.0, 25.0):
        backend.apply_class_demand(od.scaled(scale))
        res = backend.evaluate(T10)
        assert res.generated_gbps == pytest.approx(res.delivered_gbps + res.dropped_total_gbps, abs=1e-6)
        assert res.dropped_gbps.sum() == pytest.approx(res.dropped_total_gbps - res.unreachable_gbps, abs=1e-6)
        cap = np.array([ln.capacity_gbps for ln in topo.links])[:, None]
        excess = np.maximum(res.load_gbps.sum(axis=2) - cap, 0)
        assert (res.dropped_gbps.sum(axis=2) <= excess + 1e-9).all()
    assert res.dropped_total_gbps > 0  # 25x demand must overflow somewhere


def test_streaming_flows_downstream(topo, tc, backend):
    backend.apply_class_demand(_od(topo, tc, "weekend", datetime(2026, 11, 21, 20)).only("streaming"))
    res = backend.evaluate()
    for link, campus_side in [("slc-ddc--uvu-orem", "slc-ddc"), ("wsu-ogden--slc-ddc", "slc-ddc")]:
        toward_campus = _dir_load(res, link, campus_side)
        other = link.split("--")[1] if link.split("--")[0] == campus_side else link.split("--")[0]
        assert toward_campus > 5 * _dir_load(res, link, other)


def test_link_cut_reroutes_and_counts_unreachable(topo, tc, backend):
    backend.apply_class_demand(_od(topo, tc))
    backend.set_link_state("slc-slcc--wendover", False)
    res = backend.evaluate(T10)
    i = res.link_ids.index("slc-slcc--wendover")
    assert res.load_gbps[i].sum() == 0
    assert res.unreachable_nodes == ["wendover"] and res.unreachable_gbps > 0
    assert res.generated_gbps == pytest.approx(res.delivered_gbps + res.dropped_total_gbps, abs=1e-6)
    backend.set_link_state("slc-slcc--wendover", True)
    assert backend.evaluate(T10).unreachable_gbps == 0


def test_v0_interface_still_works(topo, tc, backend):
    backend.apply_demand(build_peak_matrix(topo))
    snap = backend.observe(T10)  # no class demand yet: v0 path
    assert len(snap.links) == len(topo.links)
    backend.apply_class_demand(_od(topo, tc))
    snap = backend.observe(T10)
    assert max(ls.utilization for ls in snap.links) < 1.0


def test_sessions_and_latency_are_reported(topo, tc, backend):
    backend.apply_class_demand(_od(topo, tc))
    res = backend.evaluate(T10)
    assert res.server_sessions.sum() > 0 and (res.session_capacity > 0).all()
    tx = res.classes.index("transactional")
    servers = {n for n, v in zip(res.node_ids, backend._od.node_volumes[tx]) if v > 0}
    assert {n for n, s in zip(res.node_ids, res.server_sessions) if s > 0} == servers  # only transactional servers
    assert res.tracked_sessions["telehealth"].sum() > 0
    assert (res.latency_ms > 0).all()


def test_tick_evaluation_is_fast(topo, tc, backend):
    backend.apply_class_demand(_od(topo, tc))
    backend.evaluate(T10)  # build the routing matrix once
    start = time.perf_counter()
    for _ in range(1000):
        backend.evaluate(T10)
    assert time.perf_counter() - start < 2.0  # a 24 h run at 10 s ticks is 8,640 evaluations
