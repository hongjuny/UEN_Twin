"""Run a scenario on the SimPy clock (batch: as fast as possible; live: paced to the wall clock).

Processes on one shared clock, each at its own beat:
  traffic_process          every tick (default 10 s): stochastic owned volumes + scenario overlays -> OD demand
  network_process          right after each demand update: per-direction loads, drop, latency, sessions
  telemetry_process        every 30 s (default): interval averages of totals per link/direction and per node
  class_telemetry_process  every 5 min (default): interval averages per link/direction/class
  scenario_process         scenario start/end, overlay start/end, link up/down events
Tools (1 s) and agents (minutes) will join the same clock later.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
import simpy
import yaml

from .. import topology as topology_mod
from ..engine import DEFAULT_OUT
from .clock import SimClock
from .network import DirectedFlowBackend, FlowResult
from .scenario import CompiledOverlay, Scenario, find_link, node_regions
from .telemetry import IntervalAverager, TelemetryWriter
from .traffic import DEFAULT_CLASSES, ODDemand, ODMap, TrafficClasses, TrafficGenerator, load_classes

ROOT = Path(__file__).resolve().parents[3]


def _git_version() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=5)
        return rev.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "") if rev.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class SimRun:
    def __init__(self, scenario: Scenario, seed: int | None = None, tick_s: float = 10, telemetry_s: float = 30,
                 class_telemetry_s: float = 300, speed: float | None = None, out_base: Path = DEFAULT_OUT,
                 keep_sqlite: bool | None = None, topo: topology_mod.Topology | None = None,
                 tc: TrafficClasses | None = None, on_tick: Callable[[float, FlowResult], None] | None = None):
        self.scenario = scenario
        self.seed = scenario.seed if seed is None else seed
        self.tick_s, self.telemetry_s, self.class_telemetry_s, self.speed = tick_s, telemetry_s, class_telemetry_s, speed
        self.keep_sqlite = speed is not None if keep_sqlite is None else keep_sqlite  # live mode keeps SQLite
        self.topo = topo or topology_mod.load()
        self.tc = tc or load_classes()
        self.on_tick = on_tick
        self.clock = SimClock(scenario.day, scenario.start)
        self.duration_s = scenario.duration_hours * 3600
        self.odmap = ODMap(self.topo, self.tc)
        region_of = node_regions(self.topo)
        self.overlays = [CompiledOverlay(ov, self.topo, self.tc, self.odmap, self.clock, region_of)
                         for ov in scenario.overlays]
        self.odmap.add_pairs(set().union(*(o.needed_pairs() for o in self.overlays)) if self.overlays else set())
        for o in self.overlays:
            o.finalize(self.odmap)
        self.events = [(self.clock.seconds_until(e.at), find_link(self.topo, e.link), e.up) for e in scenario.events]
        self.gen = TrafficGenerator(self.topo, self.tc, self.odmap, scenario.base_profile, np.random.default_rng(self.seed))
        self.net = DirectedFlowBackend()
        self.net.load(self.topo, self.tc)
        self._node_ids = [n.id for n in self.topo.nodes]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.out_dir = Path(out_base) / f"run_{scenario.id}_{stamp}"
        self.out_dir.mkdir(parents=True, exist_ok=False)
        self.writer = TelemetryWriter(self.out_dir / "telemetry.sqlite", [(ln.id, ln.a, ln.b) for ln in self.topo.links],
                                      self._node_ids, self.odmap.classes, self.tc.tracked_session_classes)
        self.avg, self.class_avg = IntervalAverager(), IntervalAverager()
        self.env = SimClock.make_env(speed)
        self._demand = simpy.Store(self.env, capacity=1)
        self.ticks = 0
        self.summary: dict = {}
        self._write_meta()

    def _ts(self, sim_s: float) -> str:
        return self.clock.at(sim_s).isoformat(sep=" ")

    def demand_at(self, now: float, v: np.ndarray, burst: np.ndarray | None = None) -> ODDemand:
        """Baseline OD demand plus every active overlay. Factor overlays scale the volume without its bursts, so a
        short burst is not multiplied into a long artificial plateau."""
        od = self.odmap.demand(v)
        if not self.overlays:
            return od
        steady = np.maximum(v - burst, 0) if burst is not None else v
        gbps, vols = od.gbps.copy(), od.node_volumes.copy()
        for o in self.overlays:
            e = o.extra(now, steady)
            if not e.any():
                continue
            if o.add_gbps:
                gbps[:, o.ci] += o.D @ e
            if o.add_volume:
                np.add.at(vols[o.ci], o.owner_idx, e)
        return ODDemand(od.pairs, od.classes, np.maximum(gbps, 0), od.node_ids, np.maximum(vols, 0))

    # ---- processes ----
    def traffic_process(self):
        while self.env.now < self.duration_s:
            v, burst = self.gen.step(self.clock.at(self.env.now), self.env.now, self.tick_s)
            yield self._demand.put((self.env.now, self.demand_at(self.env.now, v, burst), burst))
            yield self.env.timeout(self.tick_s)

    def network_process(self):
        while True:
            now, od, burst = yield self._demand.get()
            self.net.apply_class_demand(od)
            res = self.net.evaluate(self.clock.at(now))
            unreachable = np.isin(self._node_ids, res.unreachable_nodes).astype(float)
            self.avg.add(load_total=res.load_gbps.sum(axis=2), dropped_total=res.dropped_gbps.sum(axis=2),
                         utilization=res.utilization, latency=res.latency_ms, server_sessions=res.server_sessions,
                         session_utilization=res.session_utilization, tracked=res.tracked_sessions,
                         demand=od.node_volumes.sum(axis=0), burst=burst.sum(axis=0), unreachable=unreachable,
                         totals=[res.generated_gbps, res.delivered_gbps, res.dropped_total_gbps, res.unreachable_gbps])
            self.class_avg.add(load=res.load_gbps, dropped=res.dropped_gbps)
            self.ticks += 1
            if self.on_tick:
                self.on_tick(now, res)

    def telemetry_process(self):
        while True:
            yield self.env.timeout(self.telemetry_s)
            self._flush(self.env.now)

    def class_telemetry_process(self):
        while True:
            yield self.env.timeout(self.class_telemetry_s)
            self._flush_classes(self.env.now)

    def scenario_process(self):
        s = self.scenario
        timeline = [(0.0, "scenario", "scenario_start", {"id": s.id, "title": s.title, "seed": self.seed})]
        for o in self.overlays:
            info = {"class": o.ov.cls, "label": o.ov.label, "owners": o.owners}
            timeline.append((max(o.active_from, 0.0), "scenario", "overlay_start", info))
            if o.active_until < self.duration_s:
                timeline.append((o.active_until, "scenario", "overlay_end", info))
        for at, link, up in self.events:
            timeline.append((max(at, 0.0), "scenario", "set_link_state", {"link": link, "up": up}))
        timeline.append((self.duration_s, "scenario", "scenario_end", {"id": s.id}))
        for at, source, kind, payload in sorted(timeline, key=lambda x: x[0]):
            if at > self.env.now:
                yield self.env.timeout(at - self.env.now)
            if kind == "set_link_state":
                self.net.set_link_state(payload["link"], payload["up"])
                payload = {**payload, "unreachable_nodes": self.net.unreachable_now()}
            self.writer.event(self.env.now, self._ts(self.env.now), source, kind, payload)

    def _flush(self, sim_s: float) -> None:
        means = self.avg.pop_means()
        if means is not None:
            self.writer.write_interval(sim_s, self._ts(sim_s), means)

    def _flush_classes(self, sim_s: float) -> None:
        means = self.class_avg.pop_means()
        if means is not None:
            self.writer.write_class_interval(sim_s, self._ts(sim_s), means)

    # ---- run ----
    def run(self) -> Path:
        wall = time.perf_counter()
        # scenario first so that events at a tick's time apply before that tick's traffic
        for proc in (self.scenario_process, self.traffic_process, self.network_process, self.telemetry_process,
                     self.class_telemetry_process):
            self.env.process(proc())
        status = "finished"
        try:
            self.env.run(until=self.duration_s + 1e-9)
        except KeyboardInterrupt:  # Ctrl-C in live mode: keep what was recorded so far
            status = "interrupted"
        end = min(self.env.now, self.duration_s)
        self._flush(end)
        self._flush_classes(end)
        self.writer.close()
        self.writer.export_parquet(self.out_dir)
        if not self.keep_sqlite:
            self.writer.delete_sqlite()
        self.summary = dict(wall_seconds=round(time.perf_counter() - wall, 2), ticks=self.ticks,
                            finished=status == "finished", status=status)
        self._write_meta()
        return self.out_dir

    def _write_meta(self) -> None:
        s = self.scenario
        meta = dict(
            simulated=True, scenario=s.model_dump(by_alias=True), seed=self.seed, tick_s=self.tick_s,
            telemetry_s=self.telemetry_s, class_telemetry_s=self.class_telemetry_s, speed=self.speed,
            start=self._ts(0), duration_s=self.duration_s, code_version=_git_version(),
            parameters=dict(classes=yaml.safe_load(DEFAULT_CLASSES.read_text()),
                            traffic_profile=yaml.safe_load((ROOT / "data" / "traffic_profile.yaml").read_text()),
                            physics=yaml.safe_load((ROOT / "data" / "physics.yaml").read_text()),
                            regions=yaml.safe_load((ROOT / "data" / "regions.yaml").read_text())),
            finished=False, status="running",
        )
        meta.update(self.summary)
        (self.out_dir / "run_meta.json").write_text(json.dumps(meta, indent=2, default=str))
