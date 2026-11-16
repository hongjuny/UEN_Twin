import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from uetn_twin import topology
from uetn_twin.sim.clock import SimClock
from uetn_twin.sim.runner import SimRun
from uetn_twin.sim.scenario import Shape, list_scenarios, load_scenario, node_regions, resolve
from uetn_twin.sim.traffic import load_classes

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def topo():
    return topology.load()


@pytest.fixture(scope="module")
def tc():
    return load_classes()


def test_every_core_node_in_exactly_one_region(topo):
    spec = yaml.safe_load((Path(__file__).parents[1] / "data" / "regions.yaml").read_text())["regions"]
    listed = [c for cores in spec.values() for c in cores]
    core = [n.id for n in topo.nodes if n.tier == "core"]
    assert sorted(listed) == sorted(core)
    assert set(node_regions(topo)) == {n.id for n in topo.nodes}


def test_selectors(topo):
    reg = node_regions(topo)
    assert "uvu-orem" in resolve("region:wasatch_front", topo, reg)
    assert "kane-sd" in resolve("kind:school_district", topo, reg)
    assert resolve(["usu-logan", "tier:core"], topo, reg)[0] == "usu-logan"
    with pytest.raises(ValueError):
        resolve("region:atlantis", topo, reg)


def test_shapes():
    clock = SimClock("Monday", "06:00")
    spike, start, _ = Shape(type="spike", at="07:00", rise_min=2, peak_x=25, decay_min=45).compile(clock)
    assert spike(3500) == 1.0 and spike(3720) == pytest.approx(25.0) and 1 < spike(3720 + 45 * 60) < 25 * 0.4
    plateau, _, until = Shape(type="plateau", start="08:00", end="09:00", gbps=30, ramp_min=10).compile(clock)
    assert plateau(2 * 3600 - 1) == 0 and plateau(2 * 3600 + 300) == pytest.approx(15) and plateau(2.5 * 3600) == 30
    assert until == 3 * 3600 + 600
    mult, _, until = Shape(type="multiplier", start="18:00", end="00:00", factor=1.8).compile(SimClock("Saturday", "14:00"))
    assert mult(5 * 3600) == pytest.approx(1.8) and until == 10 * 3600  # 00:00 = midnight after the start
    with pytest.raises(ValueError):
        Shape(type="plateau", start="08:00", end="09:00")


def test_all_demo_scenarios_load(tmp_path, topo, tc):
    names = list_scenarios()
    assert {"baseline_weekday", "semester_registration_monday", "weekend_dorm_streaming", "ai_training_campaign"} <= set(names)
    for name in names:
        s = load_scenario(name)
        assert s.confidence == "assumed" and not s.events  # no failure events in demo scenarios
        SimRun(s, out_base=tmp_path / name, topo=topo, tc=tc)  # compiles overlays without error


def _short(name, start, hours, **kw):
    return load_scenario(name).model_copy(update=dict(start=start, duration_hours=hours, **kw))


def test_registration_spike_raises_server_sessions(tmp_path, topo, tc):
    rec = {}
    run = SimRun(_short("semester_registration_monday", "06:50", 0.5), out_base=tmp_path, topo=topo, tc=tc,
                 on_tick=lambda s, r: rec.__setitem__(s, r.server_sessions[r.node_ids.index("uvu-orem")]))
    run.run()
    before, peak = rec[0.0], max(v for s, v in rec.items() if 600 <= s <= 900)
    assert peak > 10 * before


def test_od_overlay_adds_its_gbps_in_one_direction(tmp_path, topo, tc):
    loads = {}

    def grab(tag):
        def on_tick(s, r):
            i = r.link_ids.index("usu-logan--wsu-ogden")
            loads.setdefault(tag, []).append((r.load_gbps[i, 0].sum(), r.load_gbps[i, 1].sum()))
        return on_tick

    base = load_scenario("baseline_weekday").model_copy(update=dict(start="09:00", duration_hours=0.2))
    with_flow = _short("semester_registration_monday", "09:00", 0.2)
    with_flow = with_flow.model_copy(update=dict(overlays=[o for o in with_flow.overlays if o.cls == "research_bulk"]))
    SimRun(base, out_base=tmp_path / "a", topo=topo, tc=tc, on_tick=grab("base")).run()
    SimRun(with_flow, out_base=tmp_path / "b", topo=topo, tc=tc, on_tick=grab("flow")).run()
    for (b_fwd, b_rev), (f_fwd, f_rev) in zip(loads["base"], loads["flow"]):
        assert f_fwd - b_fwd == pytest.approx(30.0, abs=1e-6)  # usu-logan -> wsu-ogden carries the transfer
        assert f_rev == pytest.approx(b_rev, abs=1e-9)


def test_link_cut_events(tmp_path, topo, tc):
    gaps, wendover = [], {}

    def on_tick(s, r):
        gaps.append(r.generated_gbps - r.delivered_gbps - r.dropped_total_gbps)
        wendover[s] = "wendover" in r.unreachable_nodes

    out = SimRun(load_scenario(FIXTURES / "link_cut.yaml"), out_base=tmp_path, topo=topo, tc=tc, on_tick=on_tick).run()
    assert max(abs(g) for g in gaps) < 1e-6
    assert not wendover[1190] and wendover[1200] and wendover[2390] and not wendover[2400]
    ev = pd.read_parquet(out / "events.parquet")
    cuts = ev[ev.type == "set_link_state"]
    assert len(cuts) == 4
    first = json.loads(cuts.payload.iloc[1])
    assert first["link"] == "slc-slcc--wendover" and first["unreachable_nodes"] == ["wendover"]
    links = pd.read_parquet(out / "link_telemetry.parquet")
    ring = links[(links.link_id == "usu-eastern--moab") & (links.sim_s > 630) & (links.sim_s <= 2400)]
    assert (ring.gbps == 0).all()  # down: rerouted around the ring
    eastern = links[(links.link_id == "ubtc-vernal--moab") & (links.sim_s > 630) & (links.sim_s <= 2400)]
    before = links[(links.link_id == "ubtc-vernal--moab") & (links.sim_s <= 600)]
    assert eastern.gbps.mean() > before.gbps.mean()  # Moab now reached the other way round the ring
    nodes = pd.read_parquet(out / "node_telemetry.parquet")
    w = nodes[nodes.node_id == "wendover"]
    assert w[(w.sim_s > 1230) & (w.sim_s <= 2400)].unreachable.eq(1).all()
