import json
import sqlite3
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from uetn_twin import topology
from uetn_twin.sim.runner import SimRun
from uetn_twin.sim.scenario import load_scenario
from uetn_twin.sim.traffic import ODMap, TrafficGenerator, load_classes, regions


@pytest.fixture(scope="module")
def topo():
    return topology.load()


@pytest.fixture(scope="module")
def tc():
    return load_classes()


def _short(hours=1.0, start="09:00", **kw):
    return load_scenario("baseline_weekday").model_copy(update=dict(duration_hours=hours, start=start, **kw))


def _tables(out):
    return {name: pd.read_parquet(out / f"{name}.parquet")
            for name in ("link_telemetry", "link_class_telemetry", "node_telemetry", "totals")}


def test_same_seed_same_telemetry_and_different_seed_differs(tmp_path, topo, tc):
    a = _tables(SimRun(_short(), out_base=tmp_path / "a", topo=topo, tc=tc).run())
    b = _tables(SimRun(_short(), out_base=tmp_path / "b", topo=topo, tc=tc).run())
    c = _tables(SimRun(_short(), seed=7, out_base=tmp_path / "c", topo=topo, tc=tc).run())
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])
    assert not a["totals"].generated_gbps.equals(c["totals"].generated_gbps)


def test_conservation_every_tick(tmp_path, topo, tc):
    gaps = []
    run = SimRun(_short(hours=2), out_base=tmp_path, topo=topo, tc=tc,
                 on_tick=lambda s, r: gaps.append(r.generated_gbps - r.delivered_gbps - r.dropped_total_gbps))
    run.run()
    assert len(gaps) == 720 and max(abs(g) for g in gaps) < 1e-6


def test_telemetry_files_and_interval_averages(tmp_path, topo, tc):
    out = SimRun(_short(), out_base=tmp_path, topo=topo, tc=tc).run()
    for f in ("link_telemetry.parquet", "link_class_telemetry.parquet", "node_telemetry.parquet", "events.parquet",
              "totals.parquet", "run_meta.json"):
        assert (out / f).exists()
    assert not (out / "telemetry.sqlite").exists()  # batch runs keep Parquet only
    t = _tables(out)
    assert len(t["totals"]) == 120  # 1 h / 30 s
    assert len(t["link_telemetry"]) == 120 * 2 * len(topo.links)
    assert t["link_class_telemetry"].sim_s.nunique() == 12  # 1 h / 5 min
    assert set(t["link_class_telemetry"].columns) >= {"t", "link_id", "direction", "class", "gbps", "dropped_gbps"}
    assert set(t["link_telemetry"].columns) >= {"t", "link_id", "direction", "gbps", "utilization", "dropped_gbps", "latency_ms"}
    meta = json.loads((out / "run_meta.json").read_text())
    assert meta["simulated"] is True and meta["finished"] is True and meta["seed"] == 42 and "classes" in meta["parameters"]
    ev = pd.read_parquet(out / "events.parquet")
    assert list(ev.type) == ["scenario_start", "scenario_end"]


def test_keep_sqlite_is_wal(tmp_path, topo, tc):
    out = SimRun(_short(hours=0.1), out_base=tmp_path, topo=topo, tc=tc, keep_sqlite=True).run()
    conn = sqlite3.connect(out / "telemetry.sqlite")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()


def test_fast_noise_follows_aggregation(tmp_path, topo, tc):
    """Relative 10 s jitter is small on big links and large on small ones (square-root law)."""
    rec = {"gateway": [], "kane": []}

    def on_tick(s, r):
        rec["gateway"].append(r.load_gbps[r.link_ids.index("uvu-orem--uvu-wasatch"), 0].sum())
        rec["kane"].append(r.load_gbps[r.link_ids.index("kane-sd--tdc-stgeorge"), 1].sum())

    SimRun(_short(hours=1, start="10:00"), out_base=tmp_path, topo=topo, tc=tc, on_tick=on_tick).run()

    def jitter(x):  # relative deviation from a 5-minute moving average
        x = pd.Series(x)
        return float(((x - x.rolling(30, center=True).mean()) / x.rolling(30, center=True).mean()).std())

    assert jitter(rec["gateway"]) < 0.03
    assert 0.05 < jitter(rec["kane"]) < 0.2


def test_transactional_bursts_cluster_at_class_changes(tc):
    from uetn_twin.sim.traffic import BurstSchedule

    b = tc.classes["transactional"].bursts
    assert isinstance(b.schedule, BurstSchedule)
    inside = b.rate_at(datetime(2026, 11, 16, 9, 55))
    outside = b.rate_at(datetime(2026, 11, 16, 9, 30))
    night = b.rate_at(datetime(2026, 11, 16, 3, 55))
    assert inside > 5 * outside and night == outside
    # same expected count per day as without the schedule
    total = sum(b.rate_at(datetime(2026, 11, 16) + timedelta(seconds=s)) * 10 for s in range(0, 86400, 10))
    assert total == pytest.approx(b.rate_per_hour * 24, rel=0.02)


def test_wander_is_mean_reverting_and_regionally_correlated(topo, tc):
    odmap = ODMap(topo, tc)
    gen = TrafficGenerator(topo, tc, odmap, "weekday_semester", np.random.default_rng(1))
    # isolate the wander layer: no bursts, no fast noise
    gen.burst_specs = [b.model_copy(update={"rate_per_hour": 0, "schedule": None}) for b in gen.burst_specs]
    gen.noise = gen.noise.model_copy(update={"sigma_ref": 0, "min_sigma": 0})
    t0 = datetime(2026, 11, 16, 10)
    ratios = []
    for k in range(2000):
        t = t0 + timedelta(seconds=10 * k)
        v, _ = gen.step(t, 10 * k, 10)
        base = gen.baseline(t)
        ratios.append(np.where(base > 0, v / np.where(base > 0, base, 1), np.nan))
    series = np.array(ratios)[:, odmap.classes.index("k12_instruction"), :]
    assert abs(np.nanmean(series) - 1.0) < 0.1
    reg = regions(topo)
    ids = odmap.node_ids
    ok = [i for i in range(len(ids)) if not np.isnan(series[:, i]).any()]
    same = [(i, j) for i in ok for j in ok if i < j and reg[ids[i]] == reg[ids[j]]]
    other = [(i, j) for i in ok for j in ok if i < j and reg[ids[i]] != reg[ids[j]]]

    def corr(pairs):
        return np.mean([np.corrcoef(series[:, i], series[:, j])[0, 1] for i, j in pairs[:40]])

    assert corr(same) > corr(other) + 0.2


def test_full_day_batch_runs_under_60_seconds(tmp_path, topo, tc):
    start = time.perf_counter()
    run = SimRun(load_scenario("baseline_weekday"), out_base=tmp_path, topo=topo, tc=tc)
    run.run()
    assert run.ticks == 8640
    assert time.perf_counter() - start < 60
