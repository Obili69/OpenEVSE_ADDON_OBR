"""Configuration loading for the PV Load Manager."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

from .const import (
    DEFAULT_HA_DISCOVERY_PREFIX,
    DEFAULT_HYSTERESIS_DELAY,
    DEFAULT_HYSTERESIS_THRESHOLD,
    DEFAULT_MEASUREMENT_INTERVAL,
    DEFAULT_RAMP_UP_DELAY,
    DEFAULT_TOTAL_CURRENT_LIMIT,
    DEFAULT_VOLTAGE,
)

logger = logging.getLogger(__name__)

OPTIONS_PATH = "/data/options.json"


@dataclass
class AppConfig:
    """Application configuration."""

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""

    # Per-station OpenEVSE MQTT base topics
    evse_topics: list[str] = field(
        default_factory=lambda: ["openevse/station1", "openevse/station2", "openevse/station3"]
    )

    # PV input (HA sensor entity ID)
    pv_sensor_entity_id: str = "sensor.grid_import_power"

    # Limits
    total_current_limit: int = DEFAULT_TOTAL_CURRENT_LIMIT
    voltage: int = DEFAULT_VOLTAGE

    # Algorithm tuning
    hysteresis_threshold: float = DEFAULT_HYSTERESIS_THRESHOLD
    hysteresis_delay: float = DEFAULT_HYSTERESIS_DELAY
    ramp_up_delay: float = DEFAULT_RAMP_UP_DELAY
    measurement_interval: float = DEFAULT_MEASUREMENT_INTERVAL

    # Operation
    initial_mode: str = "pv_plus_grid"

    # HA Discovery
    ha_discovery_prefix: str = DEFAULT_HA_DISCOVERY_PREFIX


def load_config() -> AppConfig:
    """Load configuration from HA add-on options or environment variables."""
    config = AppConfig()

    # Try loading from HA add-on options.json
    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH) as f:
                options = json.load(f)
            logger.info("Loaded configuration from %s", OPTIONS_PATH)
            _apply_options(config, options)
            return config
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s, falling back to env vars", OPTIONS_PATH, e)

    # Fallback: environment variables
    _apply_env(config)
    return config


def _apply_options(config: AppConfig, options: dict) -> None:
    """Apply options.json values to config."""
    if options.get("mqtt_host"):
        config.mqtt_host = options["mqtt_host"]
    if options.get("mqtt_port"):
        config.mqtt_port = int(options["mqtt_port"])
    if options.get("mqtt_username"):
        config.mqtt_username = options["mqtt_username"]
    if options.get("mqtt_password"):
        config.mqtt_password = options["mqtt_password"]
    if options.get("evse_topics"):
        config.evse_topics = options["evse_topics"]
    if options.get("pv_sensor_entity_id"):
        config.pv_sensor_entity_id = options["pv_sensor_entity_id"]
    if options.get("total_current_limit"):
        config.total_current_limit = int(options["total_current_limit"])
    if options.get("voltage"):
        config.voltage = int(options["voltage"])
    if options.get("hysteresis_threshold") is not None:
        config.hysteresis_threshold = float(options["hysteresis_threshold"])
    if options.get("hysteresis_delay") is not None:
        config.hysteresis_delay = float(options["hysteresis_delay"])
    if options.get("ramp_up_delay") is not None:
        config.ramp_up_delay = float(options["ramp_up_delay"])
    if options.get("measurement_interval") is not None:
        config.measurement_interval = float(options["measurement_interval"])
    if options.get("initial_mode"):
        config.initial_mode = options["initial_mode"]
    if options.get("ha_discovery_prefix"):
        config.ha_discovery_prefix = options["ha_discovery_prefix"]


def _apply_env(config: AppConfig) -> None:
    """Apply environment variables to config."""
    config.mqtt_host = os.environ.get("MQTT_HOST", config.mqtt_host)
    config.mqtt_port = int(os.environ.get("MQTT_PORT", config.mqtt_port))
    config.mqtt_username = os.environ.get("MQTT_USERNAME", config.mqtt_username)
    config.mqtt_password = os.environ.get("MQTT_PASSWORD", config.mqtt_password)

    evse_topics_env = os.environ.get("EVSE_TOPICS")
    if evse_topics_env:
        config.evse_topics = [t.strip() for t in evse_topics_env.split(",")]

    config.pv_sensor_entity_id = os.environ.get(
        "PV_SENSOR_ENTITY_ID", config.pv_sensor_entity_id
    )
    config.total_current_limit = int(
        os.environ.get("TOTAL_CURRENT_LIMIT", config.total_current_limit)
    )
    config.voltage = int(os.environ.get("VOLTAGE", config.voltage))
    config.initial_mode = os.environ.get("INITIAL_MODE", config.initial_mode)
