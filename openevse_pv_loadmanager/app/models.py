"""Data models for the PV Load Manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OperationMode(Enum):
    PV_ONLY = "pv_only"
    PV_PLUS_GRID = "pv_plus_grid"


class StationState(Enum):
    OFFLINE = "offline"
    IDLE = "idle"
    CHARGING = "charging"
    PAUSED = "paused"
    ERROR = "error"
    NOT_CONNECTED = "not_connected"


@dataclass
class StationConfig:
    """Configuration for a single charging station."""

    name: str
    charging_current_entity: str
    charging_status_entity: str
    charge_rate_entity: str
    override_state_entity: str
    vehicle_connected_entity: str


@dataclass
class StationStatus:
    """Runtime status of a single charging station."""

    station_id: int
    name: str
    actual_current: float = 0.0
    allocated_current: float = 0.0
    state: StationState = StationState.OFFLINE
    vehicle_connected: bool = False

    @property
    def is_active(self) -> bool:
        """Station is eligible for current allocation."""
        return self.vehicle_connected and self.state in (
            StationState.IDLE, StationState.CHARGING, StationState.PAUSED
        )

    @property
    def is_charging(self) -> bool:
        return self.state == StationState.CHARGING


@dataclass
class PVSample:
    """A single PV power measurement."""

    value: float  # Watts surplus
    timestamp: float


@dataclass
class PVData:
    """PV monitoring data."""

    surplus_w: float = 0.0
    last_update: float = 0.0
    history: list[PVSample] = field(default_factory=list)


@dataclass
class AllocationResult:
    """Result of a load allocation cycle."""

    allocations: dict[int, float]  # station_id -> amps
    total_allocated: float
    mode: OperationMode
