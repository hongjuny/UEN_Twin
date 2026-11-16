"""Run a scenario on the SimPy clock (batch: as fast as possible; live: paced to the wall clock).

Processes on one shared clock, each at its own beat:
  traffic_process    every tick (default 10 s): stochastic owned volumes -> directed OD demand
  network_process    right after each demand update: per-direction loads, drop, latency, sessions
  telemetry_process  every telemetry interval (default 30 s): interval averages to SQLite
  scenario_process   scenario start/end (overlays and events arrive in stage 3)
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
from .scenario import SCENARIO_DIR, Scenario
from .telemetry import IntervalAverager, TelemetryWriter
from .traffic import DEFAULT_CLASSES, ODMap, TrafficClasses, TrafficGenerator, load_classes

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
                 speed: float | None = None, out_base: Path = DEFAULT_OUT, topo: topology_mod.Topology | None = None,
                 tc: TrafficClasses | None = None, on_tick: Callable[[float, FlowResult], None] | None = None):
        self.scenario = scenario
        self.seed = scenario.seed if seed is None else seed
        self.tick_s, self.telemetry_s, self.speed = tick_s, telemetry_s, speed
        self.topo = topo or topology_mod.load()
        self.tc = tc or load_classes()
        self.on_tick = on_tick
        self.clock = SimClock(scenario.day, scenario.start)
        self.duration_s = scenario.duration_hours * 3600
        self.odmap = ODMap(self.topo, self.tc)
        self.gen = TrafficGenerator(self.topo, self.tc, self.odmap, scenario.base_profile, np.random.default_rng(self.seed))
        self.net = DirectedFlowBackend()
        self.net.load(self.topo, self.tc)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.out_dir = Path(out_base) / f"run_{scenario.id}_{stamp}"
        self.out_dir.mkdir(parents=True, exist_ok=False)
        self.writer = TelemetryWriter(self.out_dir / "telemetry.sqlite", [(ln.id, ln.a, ln.b) for ln in self.topo.links],
                                      [n.id for n in self.topo.nodes], self.odmap.classes, self.tc.tracked_session_classes)
        self.avg = IntervalAverager()
        self.env = SimClock.make_env(speed)
        self._demand = simpy.Store(self.env, capacity=1)
        self._burst = None
        self.ticks = 0
        self.summary: dict = {}

    def _ts(self, sim_s: float) -> str:
        return self.clock.at(sim_s).isoformat(sep=" ")

    # ---- processes ----
    def traffic_process(self):
        while self.env.now < self.duration_s:
            t = self.clock.at(self.env.now)
            v, burst = self.gen.step(t, self.env.now, self.tick_s)
            yield self._demand.put((self.env.now, self.odmap.demand(v), burst))
            yield self.env.timeout(self.tick_s)

    def network_process(self):
        while True:
            now, od, burst = yield self._demand.get()
            self.net.apply_class_demand(od)
            res = self.net.evaluate(self.clock.at(now))
            self.avg.add(load=res.load_gbps, dropped=res.dropped_gbps, utilization=res.utilization,
                         latency=res.latency_ms, server_sessions=res.server_sessions,
                         session_utilization=res.session_utilization, tracked=res.tracked_sessions,
                         demand=od.node_volumes.sum(axis=0), burst=burst.sum(axis=0),
                         totals=[res.generated_gbps, res.delivered_gbps, res.dropped_total_gbps, res.unreachable_gbps])
            self.ticks += 1
            if self.on_tick:
                self.on_tick(now, res)

    def telemetry_process(self):
        while True:
            yield self.env.timeout(self.telemetry_s)
            self._flush(self.env.now)

    def scenario_process(self):
        s = self.scenario
        self.writer.event(0, self._ts(0), "scenario", "scenario_start", {"id": s.id, "title": s.title, "seed": self.seed})
        yield self.env.timeout(self.duration_s)
        self.writer.event(self.duration_s, self._ts(self.duration_s), "scenario", "scenario_end", {"id": s.id})

    def _flush(self, sim_s: float) -> None:
        means = self.avg.pop_means()
        if means is not None:
            self.writer.write_interval(sim_s, self._ts(sim_s), means)

    # ---- run ----
    def run(self) -> Path:
        wall = time.perf_counter()
        for proc in (self.scenario_process, self.traffic_process, self.network_process, self.telemetry_process):
            self.env.process(proc())
        self.env.run(until=self.duration_s + 1e-9)
        self._flush(self.duration_s)
        self.writer.close()
        self.writer.export_parquet(self.out_dir)
        self.summary = dict(wall_seconds=round(time.perf_counter() - wall, 2), ticks=self.ticks)
        self._write_meta()
        return self.out_dir

    def _write_meta(self) -> None:
        s = self.scenario
        meta = dict(
            simulated=True, scenario=s.model_dump(), seed=self.seed, tick_s=self.tick_s, telemetry_s=self.telemetry_s,
            speed=self.speed, start=self._ts(0), duration_s=self.duration_s, code_version=_git_version(),
            parameters=dict(classes=yaml.safe_load(DEFAULT_CLASSES.read_text()),
                            traffic_profile=yaml.safe_load((ROOT / "data" / "traffic_profile.yaml").read_text()),
                            physics=yaml.safe_load((ROOT / "data" / "physics.yaml").read_text())),
            scenario_file=str((SCENARIO_DIR / f"{s.id}.yaml").relative_to(ROOT)), **self.summary,
        )
        (self.out_dir / "run_meta.json").write_text(json.dumps(meta, indent=2, default=str))
