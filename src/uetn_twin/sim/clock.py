"""Simulation clock: SimPy time is seconds since the scenario start; this maps it to a synthetic calendar time.

The calendar date is a placeholder week (starting Monday 2026-11-16) used only to get weekday and hour right.
It is never a real measurement date and the dashboard does not show it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import simpy
import simpy.rt

SYNTHETIC_MONDAY = datetime(2026, 11, 16)
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class SimClock:
    def __init__(self, day: str, start_hhmm: str):
        hh, mm = (int(x) for x in start_hhmm.split(":"))
        self.start = SYNTHETIC_MONDAY + timedelta(days=DAYS.index(day), hours=hh, minutes=mm)

    def at(self, sim_s: float) -> datetime:
        return self.start + timedelta(seconds=sim_s)

    def seconds_until(self, hhmm: str) -> float:
        """Seconds from the scenario start to HH:MM on the same synthetic day (negative if before the start)."""
        hh, mm = (int(x) for x in hhmm.split(":"))
        return (self.start.replace(hour=hh, minute=mm) - self.start).total_seconds()

    @staticmethod
    def make_env(speed: float | None = None) -> simpy.Environment:
        """Batch (as fast as possible) when speed is None; otherwise real time, `speed` simulated seconds per
        wall-clock second (60 = one simulated minute per second)."""
        if speed is None:
            return simpy.Environment()
        return simpy.rt.RealtimeEnvironment(factor=1.0 / speed, strict=False)
