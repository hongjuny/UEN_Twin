import pytest
from pydantic import ValidationError

from uetn_twin import topology
from uetn_twin.schema import Link, LinkClass, Node


def _node(id, **kw):
    base = dict(id=id, name=id, tier="core", city="X", lat=40.0, lon=-111.9, kind="pop", confidence="map")
    return Node(**{**base, **kw})


def test_confidence_required():
    with pytest.raises(ValidationError):
        Node(id="a", name="a", tier="core", city="X", lat=40, lon=-111, kind="pop")


def test_capacity_defaults_from_class():
    ln = Link(id="l", a="a", b="b", link_class=LinkClass.BACKBONE_100G, confidence="map")
    assert ln.capacity_gbps == 100.0


def test_capacity_override():
    ln = Link(id="l", a="a", b="b", link_class="ethernet_10g", capacity_gbps=2, confidence="map")
    assert ln.capacity_gbps == 2


def test_seed_data_validates():
    topo = topology.load()
    assert topology.check_consistency(topo) == []


def test_consistency_catches_problems():
    nodes = [_node("slc-level3"), _node("b")]
    links = [
        Link(id="l1", a="slc-level3", b="b", link_class="ethernet_10g", confidence="map"),
        Link(id="l2", a="b", b="slc-level3", link_class="ethernet_10g", confidence="map"),
        Link(id="l3", a="b", b="ghost", link_class="ethernet_10g", confidence="map"),
    ]
    base = topology.load()
    problems = topology.check_consistency(topology.Topology(nodes=nodes, links=links, sites=[], physics=base.physics, profile=base.profile))
    assert any("duplicates" in p for p in problems)
    assert any("ghost" in p for p in problems)
