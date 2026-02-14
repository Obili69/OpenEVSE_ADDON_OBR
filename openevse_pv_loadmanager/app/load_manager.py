"""Load Manager: core allocation algorithm with overbooking, ramp control, and hysteresis."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .config import AppConfig
from .const import (
    CLOUD_DETECTION_VARIANCE_THRESHOLD,
    CLOUD_DETECTION_WINDOW,
    MAX_RAMP_UP_STEP,
    MIN_STATION_CURRENT,
    PV_STALE_TIMEOUT,
)
from .ha_client import HAClient
from .models import (
    AllocationResult,
    OperationMode,
    PVData,
    PVSample,
    StationState,
    StationStatus,
)
from .persistence import Persistence

logger = logging.getLogger(__name__)

# Map OpenEVSE charging status strings to StationState
STATUS_MAP: dict[str, StationState] = {
    "active": StationState.IDLE,
    "charging": StationState.CHARGING,
    "sleeping": StationState.IDLE,
    "disabled": StationState.PAUSED,
    "not connected": StationState.NOT_CONNECTED,
    "error": StationState.ERROR,
}


class LoadManager:
    """Core load management algorithm using HA API."""

    def __init__(
        self,
        config: AppConfig,
        ha: HAClient,
        persistence: Persistence,
    ) -> None:
        self._config = config
        self._ha = ha
        self._persistence = persistence

        self.mode = OperationMode.PV_PLUS_GRID  # Default, overridden by mode_entity
        self._hysteresis_threshold = config.hysteresis_threshold
        self._hysteresis_delay = config.hysteresis_delay
        self._ramp_up_delay = config.ramp_up_delay

        # Station statuses
        self._stations: list[StationStatus] = [
            StationStatus(station_id=i, name=sc.name)
            for i, sc in enumerate(config.stations)
        ]

        # PV data
        self._pv = PVData()

        self._enabled = False  # Charging disabled by default

        # Per-station tracking
        self._last_allocations: dict[int, float] = {}
        self._last_ramp_up_time: dict[int, float] = {}
        self._pause_pending: dict[int, float] = {}
        self._last_sent_setpoint: dict[int, float] = {}

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore state from persistence."""
        if "mode" in state:
            try:
                self.mode = OperationMode(state["mode"])
            except ValueError:
                pass
        if "hysteresis_threshold" in state:
            self._hysteresis_threshold = float(state["hysteresis_threshold"])
        if "ramp_up_delay" in state:
            self._ramp_up_delay = float(state["ramp_up_delay"])

    async def run(self) -> None:
        """Main control loop."""
        logger.info("Load manager starting (mode=%s)", self.mode.value)

        while True:
            try:
                # Check enable switch
                enable_state = await self._ha.get_state(
                    self._config.enable_charging_entity
                )
                was_enabled = self._enabled
                self._enabled = enable_state is not None and enable_state.lower() == "on"

                if not self._enabled:
                    if was_enabled:
                        logger.info("Charging DISABLED via %s", self._config.enable_charging_entity)
                        await self._disable_all_stations()
                        self._last_sent_setpoint.clear()
                    await asyncio.sleep(self._config.measurement_interval)
                    continue

                if self._enabled and not was_enabled:
                    logger.info("Charging ENABLED via %s", self._config.enable_charging_entity)

                # Check mode switch (ON=PV+Grid, OFF=PV-Only)
                mode_state = await self._ha.get_state(self._config.mode_entity)
                if mode_state is not None:
                    new_mode = (
                        OperationMode.PV_PLUS_GRID
                        if mode_state.lower() == "on"
                        else OperationMode.PV_ONLY
                    )
                    if new_mode != self.mode:
                        logger.info("Mode changed: %s -> %s", self.mode.value, new_mode.value)
                        self.mode = new_mode

                await self._poll_all()
                result = self.compute_allocations()
                await self._apply_allocations(result)
            except Exception:
                logger.exception("Error in allocation cycle")

            await asyncio.sleep(self._config.measurement_interval)

    async def _poll_all(self) -> None:
        """Poll all station entities and PV sensor via HA API."""
        now = time.time()

        # Poll each station
        for i, sc in enumerate(self._config.stations):
            station = self._stations[i]

            # Read charging current
            current = await self._ha.get_float(sc.charging_current_entity)
            if current is not None:
                station.actual_current = current

            # Read charging status
            status_str = await self._ha.get_state(sc.charging_status_entity)
            if status_str is not None:
                station.state = STATUS_MAP.get(
                    status_str.lower(), StationState.OFFLINE
                )

            # Read vehicle connected (binary_sensor: "on" / "off")
            connected_str = await self._ha.get_state(sc.vehicle_connected_entity)
            if connected_str is not None:
                station.vehicle_connected = connected_str.lower() == "on"

        # Poll PV sensor
        pv_raw = await self._ha.get_float(self._config.pv_sensor_entity_id)
        if pv_raw is not None:
            # grid_import_power: positive = importing, negative = exporting
            # surplus = how much we're exporting (available for charging)
            surplus_w = max(0.0, -pv_raw)
            self._pv.surplus_w = surplus_w
            self._pv.last_update = now

            # Keep history for cloud detection
            self._pv.history.append(PVSample(value=surplus_w, timestamp=now))
            # Trim old samples
            cutoff = now - CLOUD_DETECTION_WINDOW
            self._pv.history = [s for s in self._pv.history if s.timestamp >= cutoff]

    def _get_available_current(self) -> float:
        """Convert PV surplus watts to available amps."""
        now = time.time()

        # Check if PV data is stale
        if now - self._pv.last_update > PV_STALE_TIMEOUT:
            logger.warning("PV data stale (%.0fs old)", now - self._pv.last_update)
            return 0.0

        # Convert watts to per-phase amps: W / (V * phases)
        watts_per_amp = self._config.voltage * self._config.phases
        surplus_amps = self._pv.surplus_w / watts_per_amp

        # Cloud detection: if high variance, be conservative
        if len(self._pv.history) >= 3:
            values = [s.value for s in self._pv.history]
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            if variance > CLOUD_DETECTION_VARIANCE_THRESHOLD:
                # Use minimum of recent readings for stability
                conservative = min(values) / watts_per_amp
                logger.debug(
                    "Cloud detected (var=%.0f), using conservative %.1fA",
                    variance, conservative,
                )
                return max(0.0, conservative)

        return max(0.0, surplus_amps)

    def compute_allocations(self) -> AllocationResult:
        """Compute current allocations for all active stations."""
        now = time.time()
        active_stations = [s for s in self._stations if s.is_active]

        if not active_stations:
            return AllocationResult(allocations={}, total_allocated=0, mode=self.mode)

        # --- STEP 1: Determine budget ---
        if self.mode == OperationMode.PV_ONLY:
            budget_amps = self._get_available_current()
        else:
            budget_amps = float(self._config.total_current_limit)

        budget_amps = min(budget_amps, float(self._config.total_current_limit))
        budget_amps = max(0.0, budget_amps)

        n = len(active_stations)

        # --- STEP 2: Equal initial distribution ---
        equal_share = budget_amps / n
        allocations: dict[int, float] = {
            s.station_id: equal_share for s in active_stations
        }

        # --- STEP 3: Overbooking ---
        # All stations keep at least equal_share as setpoint.
        # Spare capacity (limit - total actual draw) is given as bonus to
        # charging stations. Self-corrects each cycle as actual draw changes.
        limit = float(self._config.total_current_limit)
        total_actual = sum(s.actual_current for s in active_stations)
        spare = max(0.0, limit - total_actual)

        hungry_stations = [
            s.station_id for s in active_stations
            if s.is_charging and s.actual_current > 0
        ]

        if spare > 0 and hungry_stations:
            bonus_per = spare / len(hungry_stations)
            for sid in hungry_stations:
                allocations[sid] = min(equal_share + bonus_per, limit)

        # --- STEP 4: Per-station constraints ---
        for station in active_stations:
            sid = station.station_id
            alloc = allocations[sid]

            alloc = min(alloc, float(self._config.total_current_limit))

            if alloc < MIN_STATION_CURRENT:
                if station.is_charging:
                    if sid not in self._pause_pending:
                        self._pause_pending[sid] = now
                        alloc = MIN_STATION_CURRENT
                    elif now - self._pause_pending[sid] < self._hysteresis_delay:
                        alloc = MIN_STATION_CURRENT
                    else:
                        alloc = 0
                        del self._pause_pending[sid]
                else:
                    alloc = 0
            else:
                self._pause_pending.pop(sid, None)

                if station.state == StationState.PAUSED:
                    if alloc < MIN_STATION_CURRENT + self._hysteresis_threshold:
                        alloc = 0

            allocations[sid] = alloc

        # --- STEP 5: Ramp control ---
        for station in active_stations:
            sid = station.station_id
            new_alloc = allocations[sid]
            old_alloc = self._last_allocations.get(sid, 0)

            if new_alloc > old_alloc and old_alloc > 0:
                # Only ramp-limit increases after the first allocation
                last_ramp = self._last_ramp_up_time.get(sid, 0)
                if now - last_ramp < self._ramp_up_delay:
                    allocations[sid] = old_alloc
                else:
                    allocations[sid] = min(new_alloc, old_alloc + MAX_RAMP_UP_STEP)
                    self._last_ramp_up_time[sid] = now

        # Per-station logging
        for station in active_stations:
            sid = station.station_id
            logger.info(
                "  %s: alloc=%.1fA actual=%.1fA state=%s charging=%s",
                station.name, allocations[sid], station.actual_current,
                station.state.value, station.is_charging,
            )

        # Update tracking
        total_allocated = sum(allocations.values())
        self._last_allocations = dict(allocations)

        return AllocationResult(
            allocations=allocations,
            total_allocated=total_allocated,
            mode=self.mode,
        )

    async def _apply_allocations(self, result: AllocationResult) -> None:
        """Send computed setpoints to each station via HA API."""
        for station_id, amps in result.allocations.items():
            sc = self._config.stations[station_id]
            amps_rounded = round(amps)

            # Skip if setpoint hasn't changed
            if self._last_sent_setpoint.get(station_id) == amps_rounded:
                continue

            if amps_rounded <= 0:
                # Pause station
                await self._ha.set_select(sc.override_state_entity, "disabled")
                logger.info("Station %s: PAUSED", sc.name)
            else:
                # Set charge rate using correct service based on entity type
                if sc.charge_rate_entity.startswith("number."):
                    await self._ha.set_number(sc.charge_rate_entity, amps_rounded)
                else:
                    await self._ha.set_select(sc.charge_rate_entity, str(amps_rounded))
                await self._ha.set_select(sc.override_state_entity, "active")
                logger.info("Station %s: %dA", sc.name, amps_rounded)

            self._last_sent_setpoint[station_id] = amps_rounded

        # Log summary
        if result.allocations:
            logger.info(
                "Total allocated: %dA / %dA (%s)",
                round(result.total_allocated),
                self._config.total_current_limit,
                result.mode.value,
            )

    async def _disable_all_stations(self) -> None:
        """Disable charging on all stations."""
        for sc in self._config.stations:
            await self._ha.set_select(sc.override_state_entity, "disabled")
            logger.info("Station %s: DISABLED", sc.name)

    async def clear_all_overrides(self) -> None:
        """Disable all stations on shutdown."""
        for sc in self._config.stations:
            await self._ha.set_select(sc.override_state_entity, "disabled")
            logger.info("Disabled %s (shutdown)", sc.name)

    def _save_state(self) -> None:
        """Persist current state to disk."""
        self._persistence.save({
            "mode": self.mode.value,
            "hysteresis_threshold": self._hysteresis_threshold,
            "ramp_up_delay": self._ramp_up_delay,
        })
