"""Telemetry store: SQLite in WAL mode (the simulator writes while the dashboard reads), exported to Parquet.

Like real device telemetry, each row is an INTERVAL AVERAGE over its period ending at `sim_s`, not an
instantaneous value. Everything here is SIMULATED.

Tables
  link_telemetry        every 30 s (default), one row per (link, direction): total Gbps, utilization (offered
                        load), dropped Gbps, rough latency
  link_class_telemetry  every 5 min (default), one row per (link, direction, class): Gbps and dropped Gbps
  node_telemetry        every 30 s, one row per node: server sessions and their utilization, tracked-class
                        sessions, owned demand, burst part of the demand, share of the interval unreachable
  totals                every 30 s: generated / delivered / dropped / unreachable Gbps for the whole network
  events                scenario, tool and agent events (JSON payload)

Batch runs keep only the Parquet export by default (the SQLite file is deleted); live runs keep SQLite.
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
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        trk = "".join(f", {c}_sessions REAL" for c in self.tracked)
        self.conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS link_telemetry (sim_s REAL, t TEXT, link_id TEXT, from_node TEXT, to_node TEXT,
                gbps REAL, utilization REAL, dropped_gbps REAL, latency_ms REAL);
            CREATE TABLE IF NOT EXISTS link_class_telemetry (sim_s REAL, t TEXT, link_id TEXT, from_node TEXT,
                to_node TEXT, class TEXT, gbps REAL, dropped_gbps REAL);
            CREATE TABLE IF NOT EXISTS node_telemetry (sim_s REAL, t TEXT, node_id TEXT, server_sessions REAL,
                session_utilization REAL{trk}, demand_gbps REAL, burst_gbps REAL, unreachable REAL);
            CREATE TABLE IF NOT EXISTS totals (sim_s REAL, t TEXT, generated_gbps REAL, delivered_gbps REAL,
                dropped_gbps REAL, unreachable_gbps REAL);
            CREATE TABLE IF NOT EXISTS events (sim_s REAL, t TEXT, source TEXT, type TEXT, payload TEXT);
            CREATE INDEX IF NOT EXISTS ix_link ON link_telemetry (link_id, sim_s);
            CREATE INDEX IF NOT EXISTS ix_link_class ON link_class_telemetry (link_id, sim_s);
            CREATE INDEX IF NOT EXISTS ix_node ON node_telemetry (node_id, sim_s);
            CREATE INDEX IF NOT EXISTS ix_link_t ON link_telemetry (sim_s);
            CREATE INDEX IF NOT EXISTS ix_node_t ON node_telemetry (sim_s);
            CREATE INDEX IF NOT EXISTS ix_totals_t ON totals (sim_s);
        """)
        self._node_sql = f"INSERT INTO node_telemetry VALUES ({','.join('?' * (8 + len(self.tracked)))})"

    def _directions(self):
        for i, (lid, a, b) in enumerate(self.links):
            for d, (frm, to) in enumerate(((a, b), (b, a))):
                yield i, d, lid, frm, to

    def write_interval(self, sim_s: float, t: str, agg: dict) -> None:
        """agg holds interval means: load_total (L,2), dropped_total (L,2), utilization (L,2), latency (L,2),
        server_sessions (N), session_utilization (N), tracked {class: (N,)}, demand (N), burst (N),
        unreachable (N), totals (4,)."""
        rows = [(sim_s, t, lid, frm, to, float(agg["load_total"][i, d]), float(agg["utilization"][i, d]),
                 float(agg["dropped_total"][i, d]), float(agg["latency"][i, d])) for i, d, lid, frm, to in self._directions()]
        self.conn.executemany("INSERT INTO link_telemetry VALUES (?,?,?,?,?,?,?,?,?)", rows)
        nrows = [(sim_s, t, n, float(agg["server_sessions"][k]), float(agg["session_utilization"][k]),
                  *(float(agg["tracked"][c][k]) for c in self.tracked), float(agg["demand"][k]),
                  float(agg["burst"][k]), float(agg["unreachable"][k])) for k, n in enumerate(self.node_ids)]
        self.conn.executemany(self._node_sql, nrows)
        self.conn.execute("INSERT INTO totals VALUES (?,?,?,?,?,?)", (sim_s, t, *map(float, agg["totals"])))
        self.conn.commit()

    def write_class_interval(self, sim_s: float, t: str, agg: dict) -> None:
        """agg: load (L,2,C), dropped (L,2,C) interval means. Rows with no traffic are skipped."""
        rows = []
        for i, d, lid, frm, to in self._directions():
            for c, name in enumerate(self.classes):
                g, x = float(agg["load"][i, d, c]), float(agg["dropped"][i, d, c])
                if g > 0 or x > 0:
                    rows.append((sim_s, t, lid, frm, to, name, g, x))
        self.conn.executemany("INSERT INTO link_class_telemetry VALUES (?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()

    def event(self, sim_s: float, t: str, source: str, type_: str, payload: dict | None = None) -> None:
        self.conn.execute("INSERT INTO events VALUES (?,?,?,?,?)", (sim_s, t, source, type_, json.dumps(payload or {})))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def export_parquet(self, out_dir: Path) -> None:
        conn = sqlite3.connect(self.path)
        for table in ("link_telemetry", "link_class_telemetry"):
            df = pd.read_sql(f"SELECT * FROM {table}", conn)
            df.insert(3, "direction", df.from_node + "->" + df.to_node)
            df.to_parquet(out_dir / f"{table}.parquet", index=False)
        for table in ("node_telemetry", "totals", "events"):
            pd.read_sql(f"SELECT * FROM {table}", conn).to_parquet(out_dir / f"{table}.parquet", index=False)
        conn.close()

    def delete_sqlite(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)


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
