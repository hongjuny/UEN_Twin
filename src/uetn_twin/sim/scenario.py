"""Scenario files (data/scenarios/*.yaml): base profile + start time + overlays + events.

Stage 2 reads the base part (profile, day, start, duration, seed). Overlays and events are typed in stage 3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..schema import Confidence
from .clock import DAYS

SCENARIO_DIR = Path(__file__).resolve().parents[3] / "data" / "scenarios"


class Scenario(BaseModel):
    """A situation laid over a normal day. Every size value is an assumption for demonstration."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str = ""
    base_profile: Literal["weekday_semester", "weekend", "break"]
    day: Literal[DAYS] = "Monday"  # type: ignore[valid-type]
    start: str = Field(default="00:00", pattern=r"^\d{2}:\d{2}$")
    duration_hours: float = Field(gt=0)
    seed: int = 42
    confidence: Confidence
    overlays: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)


def load_scenario(name_or_path: str | Path) -> Scenario:
    """A scenario id from data/scenarios/ or a path to a YAML file."""
    p = Path(name_or_path)
    if not p.suffix:
        p = SCENARIO_DIR / f"{name_or_path}.yaml"
    if not p.exists():
        known = sorted(x.stem for x in SCENARIO_DIR.glob("*.yaml"))
        raise FileNotFoundError(f"scenario '{name_or_path}' not found; known: {known}")
    return Scenario.model_validate(yaml.safe_load(p.read_text()))
