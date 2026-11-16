"""Command line entry point: ``uetn-twin <command>``."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import engine, topology


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        topo = topology.load(Path(args.data))
    except topology.TopologyError as e:
        print("Schema errors:", *e.problems, sep="\n  ")
        return 1
    problems = topology.check_consistency(topo)
    if problems:
        print("Consistency errors:", *problems, sep="\n  ")
        return 1
    tiers = Counter(n.tier for n in topo.nodes)
    conf = Counter(x.confidence for x in [*topo.nodes, *topo.links])
    print(
        f"OK: {len(topo.nodes)} nodes ({dict(tiers)}), {len(topo.links)} links, "
        f"{len(topo.sites)} site groups; confidence {dict(conf)}"
    )
    return 0


def _load_or_exit(data: str) -> topology.Topology | None:
    try:
        topo = topology.load(Path(data))
    except topology.TopologyError as e:
        print("Schema errors:", *e.problems, sep="\n  ")
        return None
    problems = topology.check_consistency(topo)
    if problems:
        print("Consistency errors:", *problems, sep="\n  ")
        return None
    return topo


def cmd_simulate(args: argparse.Namespace) -> int:
    topo = _load_or_exit(args.data)
    if topo is None:
        return 1
    start = datetime.fromisoformat(args.start)
    run = engine.run_simulation(topo, args.hours, start, args.profile)
    out = engine.write_run(topo, run, Path(args.out))
    print(engine.summarize(topo, run))
    print(f"\nWrote {out}/snapshots.parquet")
    return 0


def _class_report(topo: topology.Topology, mode: str, at: str, top: int) -> None:
    """Directed per-class link loads at one moment of the deterministic baseline (v1-platform stage 1)."""
    import numpy as np

    from .sim.network import DirectedFlowBackend
    from .sim.traffic import baseline_volumes, build_od, load_classes

    tc = load_classes()
    hh, mm = (int(x) for x in at.split(":"))
    t = engine.DEFAULT_START.replace(hour=hh, minute=mm)
    od = build_od(topo, tc, baseline_volumes(topo, tc, mode, t))
    b = DirectedFlowBackend()
    b.load(topo, tc)
    b.apply_class_demand(od)
    res = b.evaluate(t)
    links = topo.links
    cap = np.array([ln.capacity_gbps for ln in links])

    def arrow(i: int, d: int) -> str:
        a, z = (links[i].a, links[i].b) if d == 0 else (links[i].b, links[i].a)
        return f"{a} -> {z}"

    print(f"SIMULATED baseline ({mode}, {at}); directed loads, every value assumed")
    print(f"Generated {res.generated_gbps:.1f} Gbps, delivered {res.delivered_gbps:.1f}, dropped {res.dropped_total_gbps:.2f}\n")
    for ci, name in enumerate(res.classes):
        load = res.load_gbps[:, :, ci]
        order = np.argsort(-load, axis=None)[:top]
        print(f"[{name}]  total {od.gbps[:, ci].sum():.1f} Gbps")
        for flat in order:
            i, d = divmod(int(flat), 2)
            if load[i, d] <= 0:
                break
            print(f"  {arrow(i, d):40s} {load[i, d]:7.2f} Gbps  ({load[i, d] / cap[i]:5.1%} of {cap[i]:g}G, "
                  f"direction total {res.utilization[i, d]:5.1%})")
        print()
    order = np.argsort(-res.utilization, axis=None)[:top]
    print("[all classes] most utilized directions")
    for flat in order:
        i, d = divmod(int(flat), 2)
        rev = res.utilization[i, 1 - d]
        print(f"  {arrow(i, d):40s} {res.utilization[i, d]:5.1%}  (reverse {rev:5.1%}, latency ~{res.latency_ms[i, d]:.2f} ms, rough)")
    su = res.session_utilization
    print("\n[server sessions] busiest nodes (transactional, server side)")
    for i in np.argsort(-su)[:top]:
        if res.server_sessions[i] <= 0:
            break
        print(f"  {res.node_ids[i]:20s} {res.server_sessions[i]:10,.0f} sessions  {su[i]:5.1%} of capacity {res.session_capacity[i]:,.0f}")
    for name, arr in res.tracked_sessions.items():
        busiest = ", ".join(f"{res.node_ids[i]} {arr[i]:,.0f}" for i in np.argsort(-arr)[:3])
        print(f"[{name} sessions] recorded, not capacity-checked: {busiest}")


def cmd_report(args: argparse.Namespace) -> int:
    if not (args.spof or args.classes):
        print("nothing to report; use --spof or --classes")
        return 1
    topo = _load_or_exit(args.data)
    if topo is None:
        return 1
    if args.classes:
        _class_report(topo, args.mode, args.at, args.top)
        return 0
    import pandas as pd

    df = engine.spof_table(topo)
    cols = ["link", "link_class", "unreachable_nodes", "affected_sites", "overloaded_after_reroute", "unreachable"]
    print("Single-link failures at weekday peak (sorted by affected sites, then overloaded links)\n")
    with pd.option_context("display.width", 200, "display.max_colwidth", 60):
        print(df[cols].head(args.top).to_string(index=False))
    hit = df[df.overloaded_after_reroute > 0].sort_values("overloaded_after_reroute", ascending=False)
    print("\nLinks whose failure overloads other links after rerouting (v1 scenario candidates, any rank):")
    for r in hit.itertuples():
        print(f"  {r.link} ({r.link_class}) -> overloads: {', '.join(r.overloaded_list)}")
    if hit.empty:
        print("  none")
    base = df.attrs["baseline_overloaded"]
    print(f"\nLinks already above 100% without any failure (excluded from the overload column): {base or 'none'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Batch-run a v1 scenario on the SimPy clock and print a short summary."""
    import sqlite3

    import pandas as pd

    from .sim.runner import SimRun
    from .sim.scenario import load_scenario

    if _load_or_exit(args.data) is None:
        return 1
    run = SimRun(load_scenario(args.scenario), seed=args.seed, tick_s=args.tick, telemetry_s=args.telemetry_interval,
                 out_base=Path(args.out))
    out = run.run()
    conn = sqlite3.connect(out / "telemetry.sqlite")
    tot = pd.read_sql("SELECT * FROM totals", conn)
    top = pd.read_sql("SELECT link_id, from_node, to_node, MAX(utilization) AS peak FROM link_telemetry "
                      "GROUP BY link_id, from_node, to_node ORDER BY peak DESC LIMIT 10", conn)
    sess = pd.read_sql("SELECT node_id, MAX(session_utilization) AS peak FROM node_telemetry "
                       "GROUP BY node_id ORDER BY peak DESC LIMIT 5", conn)
    conn.close()
    print(f"SIMULATED scenario '{run.scenario.id}' (seed {run.seed}): {run.ticks} ticks of {args.tick:g} s, "
          f"telemetry every {args.telemetry_interval:g} s, wall time {run.summary['wall_seconds']} s")
    print(f"Mean offered {tot.generated_gbps.mean():.1f} Gbps, peak interval {tot.generated_gbps.max():.1f} Gbps; "
          f"dropped {tot.dropped_gbps.sum() * args.telemetry_interval / 8:.1f} GB total")
    print("\nPeak utilization by direction (interval averages, offered load):")
    for r in top.itertuples():
        print(f"  {r.from_node} -> {r.to_node:28s} {r.peak:6.1%}")
    print("\nPeak server-session utilization:")
    for r in sess.itertuples():
        print(f"  {r.node_id:20s} {r.peak:6.1%}")
    print(f"\nWrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uetn-twin", description="UETN backbone digital twin")
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="check topology YAML against the schema and consistency rules")
    v.add_argument("--data", default=str(topology.DEFAULT_DIR), help="topology directory")
    v.set_defaults(func=cmd_validate)
    s = sub.add_parser("simulate", help="run the flow-level simulation and write snapshots.parquet")
    s.add_argument("--hours", type=float, default=24)
    s.add_argument("--start", default=engine.DEFAULT_START.isoformat(), help="ISO start time (default: Monday 00:00)")
    s.add_argument("--profile", default="weekday_semester", help="hourly profile name from traffic_profile.yaml")
    s.add_argument("--data", default=str(topology.DEFAULT_DIR))
    s.add_argument("--out", default=str(engine.DEFAULT_OUT))
    s.set_defaults(func=cmd_simulate)
    rr = sub.add_parser("run", help="batch-run a v1 scenario (SimPy clock) and write telemetry")
    rr.add_argument("scenario", help="scenario id in data/scenarios/ or a YAML path")
    rr.add_argument("--seed", type=int, default=None, help="override the scenario seed")
    rr.add_argument("--tick", type=float, default=10, help="traffic tick in simulated seconds")
    rr.add_argument("--telemetry-interval", type=float, default=30, help="averaging interval in simulated seconds")
    rr.add_argument("--data", default=str(topology.DEFAULT_DIR))
    rr.add_argument("--out", default=str(engine.DEFAULT_OUT))
    rr.set_defaults(func=cmd_run)
    r = sub.add_parser("report", help="reports on the topology")
    r.add_argument("--spof", action="store_true", help="single points of failure")
    r.add_argument("--classes", action="store_true", help="directed per-class link loads (v1 baseline)")
    r.add_argument("--at", default="10:00", help="HH:MM for --classes")
    r.add_argument("--mode", default="weekday_semester", help="academic mode for --classes")
    r.add_argument("--top", type=int, default=15)
    r.add_argument("--data", default=str(topology.DEFAULT_DIR))
    r.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
