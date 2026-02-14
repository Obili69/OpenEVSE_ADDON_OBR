"""Load Manager: core allocation algorithm with overbooking, ramp control, and hysteresis."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .config import AppConfig
from .const import (
    ACTUAL_TOLERANCE,
    LM_TOPIC_CONFIG_HYSTERESIS,
    LM_TOPIC_CONFIG_HYSTERESIS_SET,
    LM_TOPIC_CONFIG_RAMP_DELAY,
    LM_TOPIC_CONFIG_RAMP_DELAY_SET,
    LM_TOPIC_EVSE_ALLOCATED,
    LM_TOPIC_EVSE_SETPOINT,
    LM_TOPIC_MODE,
    LM_TOPIC_MODE_SET,
    LM_TOPIC_STATUS,
    LM_TOPIC_TOTAL_ALLOCATED,
    MAX_RAMP_UP_STEP,
    MIN_STATION_CURRENT,
    OVERBOOKING_ITERATIONS,
    SAFETY_MARGIN,
    SLACK_BUFFER,
)
from .evse_manager import EVSEManager
from .models import AllocationResult, OperationMode
from .mqtt_client import MQTTClient
from .persistence import Persistence
from .pv_monitor import PVMonitor

logger = logging.getLogger(__name__)


class LoadManager:
    """Core load management algorithm."""

    def __init__(
        self,
        config: AppConfig,
        evse: EVSEManager,
        pv: PVMonitor,
        mqtt: MQTTClient,
        persistence: Persistence,
    ) -> None:
        self._config = config
        self._evse = evse
        self._pv = pv
        self._mqtt = mqtt
        self._persistence = persistence

        self.mode = OperationMode(config.initial_mode)
        self._hysteresis_threshold = config.hysteresis_threshold
        self._hysteresis_delay = config.hysteresis_delay
        self._ramp_up_delay = config.ramp_up_delay

        # Per-station tracking
        self._last_allocations: dict[int, float] = {}
        self._last_ramp_up_time: dict[int, float] = {}
        self._pause_pending: dict[int, float] = {}  # station_id -> timestamp when pause was requested
        self._last_sent_setpoint: dict[int, float] = {}

    def setup_subscriptions(self) -> None:
        """Register MQTT subscriptions for control commands."""
        self._mqtt.register(LM_TOPIC_MODE_SET, self._on_mode_set)
        self._mqtt.register(LM_TOPIC_CONFIG_HYSTERESIS_SET, self._on_hysteresis_set)
        self._mqtt.register(LM_TOPIC_CONFIG_RAMP_DELAY_SET, self._on_ramp_delay_set)

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

    async def _on_mode_set(self, topic: str, payload: str) -> None:
        """Handle mode change command from HA."""
        try:
            new_mode = OperationMode(payload.strip().lower())
        except ValueError:
            # Handle on/off payloads from HA switch
            if payload.strip().lower() in ("on", "pv_plus_grid"):
                new_mode = OperationMode.PV_PLUS_GRID
            elif payload.strip().lower() in ("off", "pv_only"):
                new_mode = OperationMode.PV_ONLY
            else:
                logger.warning("Invalid mode: %s", payload)
                return

        if new_mode != self.mode:
            logger.info("Mode changed: %s -> %s", self.mode.value, new_mode.value)
            self.mode = new_mode
            self._save_state()

        await self._mqtt.publish(LM_TOPIC_MODE, self.mode.value, retain=True)

    async def _on_hysteresis_set(self, topic: str, payload: str) -> None:
        """Handle hysteresis threshold change from HA."""
        try:
            value = float(payload)
            if 0 <= value <= 20:
                self._hysteresis_threshold = value
                logger.info("Hysteresis threshold set to %.1fA", value)
                self._save_state()
                await self._mqtt.publish(LM_TOPIC_CONFIG_HYSTERESIS, str(value), retain=True)
        except ValueError:
            logger.warning("Invalid hysteresis value: %s", payload)

    async def _on_ramp_delay_set(self, topic: str, payload: str) -> None:
        """Handle ramp-up delay change from HA."""
        try:
            value = float(payload)
            if 0 <= value <= 300:
                self._ramp_up_delay = value
                logger.info("Ramp-up delay set to %.0fs", value)
                self._save_state()
                await self._mqtt.publish(LM_TOPIC_CONFIG_RAMP_DELAY, str(value), retain=True)
        except ValueError:
            logger.warning("Invalid ramp delay value: %s", payload)

    async def run(self) -> None:
        """Main control loop: compute and apply allocations periodically."""
        # Wait for MQTT connection
        await self._mqtt.connected.wait()
        logger.info("Load manager starting (mode=%s)", self.mode.value)

        # Publish initial state
        await self._mqtt.publish(LM_TOPIC_MODE, self.mode.value, retain=True)
        await self._mqtt.publish(LM_TOPIC_STATUS, "running", retain=True)
        await self._mqtt.publish(
            LM_TOPIC_CONFIG_HYSTERESIS, str(self._hysteresis_threshold), retain=True
        )
        await self._mqtt.publish(
            LM_TOPIC_CONFIG_RAMP_DELAY, str(self._ramp_up_delay), retain=True
        )

        while True:
            try:
                # Poll PV sensor from HA API
                await self._pv.poll()
                result = self.compute_allocations()
                await self.apply_allocations(result)
            except Exception:
                logger.exception("Error in allocation cycle")
                await self._mqtt.publish(LM_TOPIC_STATUS, "error")

            await asyncio.sleep(self._config.measurement_interval)

    def compute_allocations(self) -> AllocationResult:
        """Compute current allocations for all active stations.

        This is the core algorithm implementing:
        1. Budget determination (PV or full grid)
        2. Equal initial distribution
        3. Overbooking / dynamic reallocation
        4. Per-station constraints (min/max, pause/resume hysteresis)
        5. Ramp control (immediate down, delayed up)
        6. Safety check (emergency scale-down)
        """
        now = time.time()
        active_stations = self._evse.get_active_stations()

        if not active_stations:
            return AllocationResult(allocations={}, total_allocated=0, mode=self.mode)

        # --- STEP 1: Determine budget ---
        if self.mode == OperationMode.PV_ONLY:
            budget_amps = self._pv.get_available_current()
        else:
            budget_amps = float(self._config.total_current_limit)

        # Hard cap
        budget_amps = min(budget_amps, float(self._config.total_current_limit))
        budget_amps = max(0.0, budget_amps)

        n = len(active_stations)

        # --- STEP 2: Equal initial distribution ---
        equal_share = budget_amps / n
        allocations: dict[int, float] = {s.station_id: equal_share for s in active_stations}

        # --- STEP 3: Overbooking - dynamic reallocation ---
        for _ in range(OVERBOOKING_ITERATIONS):
            slack = 0.0
            hungry_stations: list[int] = []

            for station in active_stations:
                sid = station.station_id
                alloc = allocations[sid]
                actual = station.actual_current

                # Station has slack if it draws significantly less than allocated
                if actual < alloc - ACTUAL_TOLERANCE and actual > 0:
                    unused = alloc - actual - SLACK_BUFFER
                    if unused > 0:
                        slack += unused
                        allocations[sid] = actual + SLACK_BUFFER
                else:
                    hungry_stations.append(sid)

            if slack > 0 and hungry_stations:
                bonus = slack / len(hungry_stations)
                for sid in hungry_stations:
                    allocations[sid] += bonus

        # --- STEP 4: Per-station constraints ---
        for station in active_stations:
            sid = station.station_id
            alloc = allocations[sid]

            # Cap at total limit per station (single station can use all)
            alloc = min(alloc, float(self._config.total_current_limit))

            # Minimum threshold with hysteresis
            if alloc < MIN_STATION_CURRENT:
                if station.is_charging:
                    # Delay pause using hysteresis
                    if sid not in self._pause_pending:
                        self._pause_pending[sid] = now
                        alloc = MIN_STATION_CURRENT  # Hold at minimum during delay
                    elif now - self._pause_pending[sid] < self._hysteresis_delay:
                        alloc = MIN_STATION_CURRENT  # Still in delay period
                    else:
                        alloc = 0  # Delay expired, pause
                        del self._pause_pending[sid]
                else:
                    alloc = 0  # Not charging, pause immediately
            else:
                # Clear pending pause
                self._pause_pending.pop(sid, None)

                # Resume hysteresis: need extra margin above minimum to resume
                if station.state.value == "paused":
                    if alloc < MIN_STATION_CURRENT + self._hysteresis_threshold:
                        alloc = 0  # Stay paused until enough headroom

            allocations[sid] = alloc

        # --- STEP 5: Ramp control ---
        for station in active_stations:
            sid = station.station_id
            new_alloc = allocations[sid]
            old_alloc = self._last_allocations.get(sid, 0)

            if new_alloc > old_alloc:
                # Ramp UP: delayed, limited step size
                last_ramp = self._last_ramp_up_time.get(sid, 0)
                if now - last_ramp < self._ramp_up_delay:
                    allocations[sid] = old_alloc  # Hold previous value
                else:
                    allocations[sid] = min(new_alloc, old_alloc + MAX_RAMP_UP_STEP)
                    self._last_ramp_up_time[sid] = now
            # Ramp DOWN: immediate (no delay for safety)

        # --- STEP 6: Safety check on actual draw ---
        total_actual = sum(s.actual_current for s in active_stations)
        limit = float(self._config.total_current_limit)

        if total_actual > limit - SAFETY_MARGIN:
            # Emergency: proportionally scale down ALL setpoints
            if total_actual > 0:
                scale = (limit - SAFETY_MARGIN) / total_actual
                logger.warning(
                    "SAFETY: total actual %.1fA near limit %dA, scaling down (factor=%.2f)",
                    total_actual,
                    self._config.total_current_limit,
                    scale,
                )
                for sid in allocations:
                    allocations[sid] = allocations[sid] * scale

        # Update tracking
        total_allocated = sum(allocations.values())
        self._last_allocations = dict(allocations)

        return AllocationResult(
            allocations=allocations,
            total_allocated=total_allocated,
            mode=self.mode,
        )

    async def apply_allocations(self, result: AllocationResult) -> None:
        """Send computed setpoints to each station and publish state."""
        for station_id, amps in result.allocations.items():
            # Send setpoint to EVSE
            await self._evse.set_current(station_id, amps)

            # Publish for HA visibility
            amps_rounded = round(amps)
            await self._mqtt.publish(
                LM_TOPIC_EVSE_SETPOINT.format(station_id), str(amps_rounded)
            )
            await self._mqtt.publish(
                LM_TOPIC_EVSE_ALLOCATED.format(station_id), str(amps_rounded)
            )

        # Publish global state
        await self._mqtt.publish(
            LM_TOPIC_TOTAL_ALLOCATED, str(round(result.total_allocated))
        )
        await self._mqtt.publish(LM_TOPIC_MODE, result.mode.value, retain=True)
        await self._mqtt.publish(LM_TOPIC_STATUS, "running", retain=True)

    def _save_state(self) -> None:
        """Persist current state to disk."""
        self._persistence.save({
            "mode": self.mode.value,
            "hysteresis_threshold": self._hysteresis_threshold,
            "ramp_up_delay": self._ramp_up_delay,
        })
