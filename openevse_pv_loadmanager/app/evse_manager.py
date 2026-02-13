"""EVSE Manager: per-station state tracking and OpenEVSE command dispatch."""

from __future__ import annotations

import json
import logging
import time

from .config import AppConfig
from .const import (
    EVSE_OFFLINE_TIMEOUT,
    EVSE_STATE_CHARGING,
    EVSE_STATE_CONNECTED,
    EVSE_STATE_DISABLED,
    EVSE_STATE_ERROR,
    EVSE_STATE_NOT_CONNECTED,
    EVSE_TOPIC_AMP,
    EVSE_TOPIC_OVERRIDE,
    EVSE_TOPIC_PILOT,
    EVSE_TOPIC_STATE,
    EVSE_TOPIC_WH,
    LM_TOPIC_EVSE_ACTUAL,
    LM_TOPIC_EVSE_ENERGY,
    LM_TOPIC_EVSE_STATE,
    MIN_STATION_CURRENT,
)
from .models import EVSEState, StationState
from .mqtt_client import MQTTClient

logger = logging.getLogger(__name__)


class EVSEManager:
    """Manages state and commands for all OpenEVSE stations."""

    def __init__(self, config: AppConfig, mqtt: MQTTClient) -> None:
        self._config = config
        self._mqtt = mqtt
        self.stations: dict[int, EVSEState] = {}
        self._last_sent_setpoint: dict[int, float] = {}

        # Initialize stations from config
        for idx, base_topic in enumerate(config.evse_topics):
            station_id = idx + 1
            self.stations[station_id] = EVSEState(
                station_id=station_id,
                base_topic=base_topic.rstrip("/"),
            )
            self._last_sent_setpoint[station_id] = -1

    def setup_subscriptions(self) -> None:
        """Register MQTT subscriptions for all stations."""
        for station_id, station in self.stations.items():
            base = station.base_topic

            # Subscribe to OpenEVSE topics
            self._mqtt.register(
                f"{base}/{EVSE_TOPIC_AMP}",
                self._make_handler(station_id, self._on_amp),
            )
            self._mqtt.register(
                f"{base}/{EVSE_TOPIC_PILOT}",
                self._make_handler(station_id, self._on_pilot),
            )
            self._mqtt.register(
                f"{base}/{EVSE_TOPIC_STATE}",
                self._make_handler(station_id, self._on_state),
            )
            self._mqtt.register(
                f"{base}/{EVSE_TOPIC_WH}",
                self._make_handler(station_id, self._on_wh),
            )

    def _make_handler(self, station_id: int, handler):
        """Create a topic handler bound to a specific station."""

        async def _handler(topic: str, payload: str) -> None:
            await handler(station_id, payload)

        return _handler

    async def _on_amp(self, station_id: int, payload: str) -> None:
        """Handle actual current update from OpenEVSE.

        OpenEVSE publishes current in milliamps.
        """
        station = self.stations[station_id]
        try:
            # OpenEVSE amp topic: milliamps -> amps
            station.actual_current = float(payload) / 1000.0
        except ValueError:
            logger.warning("Invalid amp value from station %d: %s", station_id, payload)
            return
        station.last_seen = time.time()

        # Republish for HA visibility
        await self._mqtt.publish(
            LM_TOPIC_EVSE_ACTUAL.format(station_id),
            f"{station.actual_current:.1f}",
        )

    async def _on_pilot(self, station_id: int, payload: str) -> None:
        """Handle pilot current update."""
        station = self.stations[station_id]
        try:
            station.pilot_current = float(payload)
        except ValueError:
            return
        station.last_seen = time.time()

    async def _on_state(self, station_id: int, payload: str) -> None:
        """Handle EVSE state code update.

        Maps OpenEVSE state codes to StationState enum.
        """
        station = self.stations[station_id]
        try:
            code = int(payload)
        except ValueError:
            logger.warning("Invalid state from station %d: %s", station_id, payload)
            return

        station.evse_state_code = code
        station.last_seen = time.time()

        # Map state code
        old_state = station.state
        if code == EVSE_STATE_NOT_CONNECTED:
            station.state = StationState.NOT_CONNECTED
        elif code == EVSE_STATE_CONNECTED:
            station.state = StationState.IDLE
        elif code == EVSE_STATE_CHARGING:
            station.state = StationState.CHARGING
        elif code == EVSE_STATE_ERROR:
            station.state = StationState.ERROR
        elif code == EVSE_STATE_DISABLED:
            station.state = StationState.PAUSED
        else:
            station.state = StationState.OFFLINE

        if station.state != old_state:
            logger.info(
                "Station %d state: %s -> %s (code %d)",
                station_id,
                old_state.value,
                station.state.value,
                code,
            )

        # Republish for HA visibility
        await self._mqtt.publish(
            LM_TOPIC_EVSE_STATE.format(station_id),
            station.state.value,
            retain=True,
        )

    async def _on_wh(self, station_id: int, payload: str) -> None:
        """Handle session energy update."""
        station = self.stations[station_id]
        try:
            station.session_energy_wh = float(payload)
        except ValueError:
            return
        station.last_seen = time.time()

        # Republish as kWh for HA
        await self._mqtt.publish(
            LM_TOPIC_EVSE_ENERGY.format(station_id),
            f"{station.session_energy_wh / 1000.0:.2f}",
        )

    async def set_current(self, station_id: int, amps: float) -> None:
        """Send a current setpoint to an OpenEVSE station via override.

        Args:
            station_id: Station identifier (1-based).
            amps: Target current in amperes. 0 means pause/disable.
        """
        station = self.stations.get(station_id)
        if not station:
            return

        amps_rounded = round(amps)

        # Skip if unchanged
        if self._last_sent_setpoint.get(station_id) == amps_rounded:
            return

        base = station.base_topic
        topic = f"{base}/{EVSE_TOPIC_OVERRIDE}"

        if amps_rounded < MIN_STATION_CURRENT:
            # Pause: disable the station
            payload = json.dumps({"state": "disabled"})
            logger.info("Station %d: PAUSE (below %dA minimum)", station_id, MIN_STATION_CURRENT)
        else:
            # Set active with target current
            payload = json.dumps({
                "state": "active",
                "charge_current": amps_rounded,
            })
            logger.info("Station %d: set current to %dA", station_id, amps_rounded)

        await self._mqtt.publish(topic, payload)
        self._last_sent_setpoint[station_id] = amps_rounded
        station.allocated_current = amps
        station.last_setpoint_change = time.time()

    async def clear_all_overrides(self) -> None:
        """Clear overrides on all stations (used during shutdown).

        Sends a clear override so stations fall back to their default pilot current.
        OpenEVSE clears the override when 'state' is set to 'auto'.
        """
        for station_id, station in self.stations.items():
            base = station.base_topic
            topic = f"{base}/{EVSE_TOPIC_OVERRIDE}"
            payload = json.dumps({"state": "auto"})
            await self._mqtt.publish(topic, payload)
            self._last_sent_setpoint[station_id] = -1
            logger.info("Station %d: override cleared (auto)", station_id)

    def get_active_stations(self) -> list[EVSEState]:
        """Return stations that are connected and eligible for charging."""
        now = time.time()
        active = []
        for station in self.stations.values():
            if not self.is_online(station.station_id):
                if station.state != StationState.OFFLINE:
                    station.state = StationState.OFFLINE
                    logger.warning("Station %d marked OFFLINE (timeout)", station.station_id)
                continue
            if station.is_active:
                active.append(station)
        return active

    def is_online(self, station_id: int) -> bool:
        """Check if a station has been seen recently."""
        station = self.stations.get(station_id)
        if not station or station.last_seen == 0:
            return False
        return (time.time() - station.last_seen) < EVSE_OFFLINE_TIMEOUT
