"""Telemetry store: SQLite in WAL mode (the simulator writes while the dashboard reads), exported to Parquet at the end.

Like real device telemetry, each row is an INTERVAL AVERAGE over the telemetry period (default 30 s) ending at
`sim_s`, not an instantaneous value. Everything here is SIMULATED.

Tables
  link_telemetry  one row per (interval, link, direction): total and per-class Gbps, utilization (offered load),
                  dropped Gbps (total and per class), rough latency
  node_telemetry  one row per (interval, node): server sessions and their utilization, tracked-class sessions,
                  owned demand, burst part of the demand
  totals          one row per interval: generated / delivered / dropped / unreachable Gbps for the whole network
  events          scenario, tool and agent events (JSON payload)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


class TelemetryWriter:
    def __init__(self, path: Path, links: list[tuple[str, str, str]], node_ids: list[str], classes: tuple[str, ...],
                 tracked_session_classes: list[str]):
        """links: (link_id, a, b) in topology order."""
        self.path = Path(path)
        self.links, self.node_ids, self.classes = links, node_ids, classes
        self.tracked = tracked_session_classes
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        cls = "".join(f", gbps_{c} REAL" for c in classes) + "".join(f", dropped_{c} REAL" for c in classes)
        trk = "".join(f", {c}_sessions REAL" for c in self.tracked)
        self.conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS link_telemetry (sim_s REAL, t TEXT, link_id TEXT, from_node TEXT, to_node TEXT,
                gbps REAL, utilization REAL, dropped_gbps REAL, latency_ms REAL{cls});
            CREATE TABLE IF NOT EXISTS node_telemetry (sim_s REAL, t TEXT, node_id TEXT, server_sessions REAL,
                session_utilization REAL{trk}, demand_gbps REAL, burst_gbps REAL);
            CREATE TABLE IF NOT EXISTS totals (sim_s REAL, t TEXT, generated_gbps REAL, delivered_gbps REAL,
                dropped_gbps REAL, unreachable_gbps REAL);
            CREATE TABLE IF NOT EXISTS events (sim_s REAL, t TEXT, source TEXT, type TEXT, payload TEXT);
            CREATE INDEX IF NOT EXISTS ix_link ON link_telemetry (link_id, sim_s);
            CREATE INDEX IF NOT EXISTS ix_node ON node_telemetry (node_id, sim_s);
        """)
        self._link_sql = (f"INSERT INTO link_telemetry VALUES ({','.join('?' * (9 + 2 * len(classes)))})")
        self._node_sql = f"INSERT INTO node_telemetry VALUES ({','.join('?' * (7 + len(self.tracked)))})"

    def write_interval(self, sim_s: float, t: str, agg: dict) -> None:
        """agg holds interval means: load (L,2,C), dropped (L,2,C), utilization (L,2), latency (L,2),
        server_sessions (N), session_utilization (N), tracked {class: (N,)}, demand (N), burst (N), totals (4,)."""
        rows = []
        for i, (lid, a, b) in enumerate(self.links):
            for d, (frm, to) in enumerate(((a, b), (b, a))):
                load, drop = agg["load"][i, d], agg["dropped"][i, d]
                rows.append((sim_s, t, lid, frm, to, float(load.sum()), float(agg["utilization"][i, d]),
                             float(drop.sum()), float(agg["latency"][i, d]), *map(float, load), *map(float, drop)))
        self.conn.executemany(self._link_sql, rows)
        nrows = [(sim_s, t, n, float(agg["server_sessions"][k]), float(agg["session_utilization"][k]),
                  *(float(agg["tracked"][c][k]) for c in self.tracked), float(agg["demand"][k]), float(agg["burst"][k]))
                 for k, n in enumerate(self.node_ids)]
        self.conn.executemany(self._node_sql, nrows)
        self.conn.execute("INSERT INTO totals VALUES (?,?,?,?,?,?)", (sim_s, t, *map(float, agg["totals"])))
        self.conn.commit()

    def event(self, sim_s: float, t: str, source: str, type_: str, payload: dict | None = None) -> None:
        self.conn.execute("INSERT INTO events VALUES (?,?,?,?,?)", (sim_s, t, source, type_, json.dumps(payload or {})))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def export_parquet(self, out_dir: Path) -> None:
        """Long-format Parquet files for analysis (one row per link, direction and class)."""
        conn = sqlite3.connect(self.path)
        links = pd.read_sql("SELECT * FROM link_telemetry", conn)
        links["direction"] = links.from_node + "->" + links.to_node
        long = []
        for c in self.classes:
            part = links[["sim_s", "t", "link_id", "direction", "utilization", "latency_ms"]].copy()
            part["class"] = c
            part["gbps"] = links[f"gbps_{c}"]
            part["dropped_gbps"] = links[f"dropped_{c}"]
            long.append(part)
        cols = ["sim_s", "t", "link_id", "direction", "class", "gbps", "utilization", "dropped_gbps", "latency_ms"]
        pd.concat(long, ignore_index=True)[cols].to_parquet(out_dir / "link_telemetry.parquet", index=False)
        pd.read_sql("SELECT * FROM node_telemetry", conn).to_parquet(out_dir / "node_telemetry.parquet", index=False)
        pd.read_sql("SELECT * FROM totals", conn).to_parquet(out_dir / "totals.parquet", index=False)
        pd.read_sql("SELECT * FROM events", conn).to_parquet(out_dir / "events.parquet", index=False)
        conn.close()


class IntervalAverager:
    """Sums tick results and returns their means at the end of each telemetry interval."""

    def __init__(self):
        self.n = 0
        self.s: dict = {}

    def add(self, **values) -> None:
        for k, v in values.items():
            if isinstance(v, dict):
                d = self.s.setdefault(k, {})
                for kk, vv in v.items():
                    d[kk] = d.get(kk, 0) + np.asarray(vv, dtype=float)
            else:
                self.s[k] = self.s.get(k, 0) + np.asarray(v, dtype=float)
        self.n += 1

    def pop_means(self) -> dict | None:
        if not self.n:
            return None
        out = {k: ({kk: vv / self.n for kk, vv in v.items()} if isinstance(v, dict) else v / self.n)
               for k, v in self.s.items()}
        self.n, self.s = 0, {}
        return out
