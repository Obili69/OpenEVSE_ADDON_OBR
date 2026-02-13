"""Data models for the PV Load Manager."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class OperationMode(Enum):
    """Load manager operation modes."""

    PV_ONLY = "pv_only"
    PV_PLUS_GRID = "pv_plus_grid"


class StationState(Enum):
    """Charging station states."""

    OFFLINE = "offline"
    IDLE = "idle"  # Connected, not charging
    CHARGING = "charging"
    PAUSED = "paused"  # Below 6A, temporarily paused
    ERROR = "error"
    NOT_CONNECTED = "not_connected"


@dataclass
class EVSEState:
    """State of a single OpenEVSE charging station."""

    station_id: int
    base_topic: str
    actual_current: float = 0.0  # From OpenEVSE amp topic (A)
    pilot_current: float = 0.0  # Pilot signal (A)
    allocated_current: float = 0.0  # What we set as setpoint (A)
    session_energy_wh: float = 0.0  # Session energy (Wh)
    evse_state_code: int = 0  # Raw OpenEVSE state code
    state: StationState = StationState.OFFLINE
    last_seen: float = 0.0  # Timestamp of last MQTT message
    last_setpoint_change: float = 0.0  # Timestamp of last setpoint change

    @property
    def is_active(self) -> bool:
        """Station is eligible for current allocation."""
        return self.state in (StationState.IDLE, StationState.CHARGING, StationState.PAUSED)

    @property
    def is_charging(self) -> bool:
        return self.state == StationState.CHARGING


@dataclass
class PVSample:
    """A single PV power measurement."""

    value: float  # Watts
    timestamp: float


@dataclass
class PVData:
    """PV monitoring data."""

    grid_export_power_w: float = 0.0  # Positive = export/surplus
    last_update: float = 0.0
    history: list[PVSample] = field(default_factory=list)


@dataclass
class AllocationResult:
    """Result of a load allocation cycle."""

    allocations: dict[int, float]  # station_id -> amperes
    total_allocated: float
    mode: OperationMode
