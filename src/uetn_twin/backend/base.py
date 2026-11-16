"""Backend abstraction. The CLI, engine and dashboard only see this class, so a higher-fidelity
backend (e.g. Containerlab) can be added later without touching them."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..schema import Snapshot
from ..topology import Topology
from ..traffic import DemandMatrix


class NetworkBackend(ABC):
    @abstractmethod
    def load(self, topology: Topology) -> None:
        """Build the network from topology data. All links start up."""

    @abstractmethod
    def set_link_state(self, link_id: str, up: bool) -> None:
        """Bring a link up or down (failure-injection plumbing; no scenarios yet)."""

    @abstractmethod
    def apply_demand(self, matrix: DemandMatrix) -> None:
        """Set the traffic currently offered to the network."""

    @abstractmethod
    def observe(self, t: datetime) -> Snapshot:
        """Return the network state at time t for the current links and demand."""
