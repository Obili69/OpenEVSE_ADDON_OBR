"""HA MQTT Discovery: publish auto-discovery configs for Home Assistant entities."""

from __future__ import annotations

import json
import logging

from .config import AppConfig
from .const import (
    DEVICE_IDENTIFIER,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    LM_TOPIC_CONFIG_HYSTERESIS,
    LM_TOPIC_CONFIG_HYSTERESIS_SET,
    LM_TOPIC_CONFIG_RAMP_DELAY,
    LM_TOPIC_CONFIG_RAMP_DELAY_SET,
    LM_TOPIC_EVSE_ACTUAL,
    LM_TOPIC_EVSE_ENERGY,
    LM_TOPIC_EVSE_SETPOINT,
    LM_TOPIC_EVSE_STATE,
    LM_TOPIC_MODE,
    LM_TOPIC_MODE_SET,
    LM_TOPIC_STATUS,
    LM_TOPIC_TOTAL_ALLOCATED,
)
from .mqtt_client import MQTTClient

logger = logging.getLogger(__name__)


def _device_info() -> dict:
    """Common device info block for all entities."""
    return {
        "identifiers": [DEVICE_IDENTIFIER],
        "name": DEVICE_NAME,
        "manufacturer": DEVICE_MANUFACTURER,
        "model": DEVICE_MODEL,
    }


class HADiscoveryPublisher:
    """Publishes MQTT Discovery configs so HA auto-creates entities."""

    def __init__(self, config: AppConfig, mqtt: MQTTClient) -> None:
        self._config = config
        self._mqtt = mqtt
        self._prefix = config.ha_discovery_prefix

    async def publish_on_connect(self, mqtt: MQTTClient) -> None:
        """Wait for MQTT connection, then publish all discovery configs."""
        await mqtt.connected.wait()
        await self.publish_all()

    async def publish_all(self) -> None:
        """Publish discovery configs for all entities."""
        logger.info("Publishing HA MQTT Discovery configs")

        await self._publish_mode_switch()
        await self._publish_status_sensor()
        await self._publish_total_allocated_sensor()

        # Per-station sensors
        num_stations = len(self._config.evse_topics)
        for station_id in range(1, num_stations + 1):
            await self._publish_station_sensors(station_id)

        # Config number entities
        await self._publish_hysteresis_number()
        await self._publish_ramp_delay_number()

        logger.info("HA Discovery configs published (%d stations)", num_stations)

    async def _publish_mode_switch(self) -> None:
        """Publish discovery config for the operation mode switch."""
        config = {
            "name": "PV Load Manager Mode",
            "unique_id": f"{DEVICE_IDENTIFIER}_mode",
            "command_topic": LM_TOPIC_MODE_SET,
            "state_topic": LM_TOPIC_MODE,
            "payload_on": "pv_plus_grid",
            "payload_off": "pv_only",
            "state_on": "pv_plus_grid",
            "state_off": "pv_only",
            "icon": "mdi:solar-power-variant",
            "device": _device_info(),
        }
        topic = f"{self._prefix}/switch/{DEVICE_IDENTIFIER}_mode/config"
        await self._mqtt.publish(topic, json.dumps(config), retain=True)

    async def _publish_status_sensor(self) -> None:
        """Publish discovery config for the load manager status sensor."""
        config = {
            "name": "Load Manager Status",
            "unique_id": f"{DEVICE_IDENTIFIER}_status",
            "state_topic": LM_TOPIC_STATUS,
            "icon": "mdi:information-outline",
            "device": _device_info(),
        }
        topic = f"{self._prefix}/sensor/{DEVICE_IDENTIFIER}_status/config"
        await self._mqtt.publish(topic, json.dumps(config), retain=True)

    async def _publish_total_allocated_sensor(self) -> None:
        """Publish discovery config for total allocated current sensor."""
        config = {
            "name": "Total Allocated Current",
            "unique_id": f"{DEVICE_IDENTIFIER}_total_allocated",
            "state_topic": LM_TOPIC_TOTAL_ALLOCATED,
            "unit_of_measurement": "A",
            "device_class": "current",
            "state_class": "measurement",
            "icon": "mdi:current-ac",
            "device": _device_info(),
        }
        topic = f"{self._prefix}/sensor/{DEVICE_IDENTIFIER}_total_allocated/config"
        await self._mqtt.publish(topic, json.dumps(config), retain=True)

    async def _publish_station_sensors(self, station_id: int) -> None:
        """Publish discovery configs for a single station's sensors."""
        sensors = [
            {
                "name": f"EVSE {station_id} Setpoint",
                "unique_id": f"{DEVICE_IDENTIFIER}_evse{station_id}_setpoint",
                "state_topic": LM_TOPIC_EVSE_SETPOINT.format(station_id),
                "unit_of_measurement": "A",
                "device_class": "current",
                "state_class": "measurement",
                "icon": "mdi:flash",
            },
            {
                "name": f"EVSE {station_id} Actual Current",
                "unique_id": f"{DEVICE_IDENTIFIER}_evse{station_id}_actual",
                "state_topic": LM_TOPIC_EVSE_ACTUAL.format(station_id),
                "unit_of_measurement": "A",
                "device_class": "current",
                "state_class": "measurement",
                "icon": "mdi:flash",
            },
            {
                "name": f"EVSE {station_id} State",
                "unique_id": f"{DEVICE_IDENTIFIER}_evse{station_id}_state",
                "state_topic": LM_TOPIC_EVSE_STATE.format(station_id),
                "icon": "mdi:ev-station",
            },
            {
                "name": f"EVSE {station_id} Session Energy",
                "unique_id": f"{DEVICE_IDENTIFIER}_evse{station_id}_energy",
                "state_topic": LM_TOPIC_EVSE_ENERGY.format(station_id),
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "total_increasing",
                "icon": "mdi:battery-charging",
            },
        ]

        for sensor in sensors:
            sensor["device"] = _device_info()
            uid = sensor["unique_id"]
            topic = f"{self._prefix}/sensor/{uid}/config"
            await self._mqtt.publish(topic, json.dumps(sensor), retain=True)

    async def _publish_hysteresis_number(self) -> None:
        """Publish discovery config for hysteresis threshold number entity."""
        config = {
            "name": "Hysteresis Threshold",
            "unique_id": f"{DEVICE_IDENTIFIER}_hysteresis",
            "command_topic": LM_TOPIC_CONFIG_HYSTERESIS_SET,
            "state_topic": LM_TOPIC_CONFIG_HYSTERESIS,
            "min": 0,
            "max": 10,
            "step": 0.5,
            "unit_of_measurement": "A",
            "icon": "mdi:sine-wave",
            "device": _device_info(),
        }
        topic = f"{self._prefix}/number/{DEVICE_IDENTIFIER}_hysteresis/config"
        await self._mqtt.publish(topic, json.dumps(config), retain=True)

    async def _publish_ramp_delay_number(self) -> None:
        """Publish discovery config for ramp-up delay number entity."""
        config = {
            "name": "Ramp-Up Delay",
            "unique_id": f"{DEVICE_IDENTIFIER}_ramp_delay",
            "command_topic": LM_TOPIC_CONFIG_RAMP_DELAY_SET,
            "state_topic": LM_TOPIC_CONFIG_RAMP_DELAY,
            "min": 0,
            "max": 120,
            "step": 5,
            "unit_of_measurement": "s",
            "icon": "mdi:timer-outline",
            "device": _device_info(),
        }
        topic = f"{self._prefix}/number/{DEVICE_IDENTIFIER}_ramp_delay/config"
        await self._mqtt.publish(topic, json.dumps(config), retain=True)
