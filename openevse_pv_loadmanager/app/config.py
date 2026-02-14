"""Configuration loading for the PV Load Manager."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

from .const import (
    DEFAULT_HYSTERESIS_DELAY,
    DEFAULT_HYSTERESIS_THRESHOLD,
    DEFAULT_MEASUREMENT_INTERVAL,
    DEFAULT_PHASES,
    DEFAULT_RAMP_UP_DELAY,
    DEFAULT_TOTAL_CURRENT_LIMIT,
    DEFAULT_VOLTAGE,
)
from .models import StationConfig

logger = logging.getLogger(__name__)

OPTIONS_PATH = "/data/options.json"


@dataclass
class AppConfig:
    """Application configuration."""

    stations: list[StationConfig] = field(default_factory=list)
    enable_charging_entity: str = "switch.openevse_pv_load_manager_enable_charging"
    mode_entity: str = "switch.openevse_pv_load_manager_pv_load_manager_mode"
    pv_sensor_entity_id: str = "sensor.grid_import_power"
    total_current_limit: int = DEFAULT_TOTAL_CURRENT_LIMIT
    voltage: int = DEFAULT_VOLTAGE
    phases: int = DEFAULT_PHASES
    hysteresis_threshold: float = DEFAULT_HYSTERESIS_THRESHOLD
    hysteresis_delay: float = DEFAULT_HYSTERESIS_DELAY
    ramp_up_delay: float = DEFAULT_RAMP_UP_DELAY
    measurement_interval: float = DEFAULT_MEASUREMENT_INTERVAL


def load_config() -> AppConfig:
    """Load configuration from HA add-on options."""
    config = AppConfig()

    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH) as f:
                options = json.load(f)
            logger.info("Loaded configuration from %s", OPTIONS_PATH)
            _apply_options(config, options)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s", OPTIONS_PATH, e)

    if not config.stations:
        logger.warning("No stations configured!")

    return config


def _apply_options(config: AppConfig, options: dict) -> None:
    """Apply options.json values to config."""
    # Parse station configs
    if options.get("stations"):
        config.stations = []
        for s in options["stations"]:
            config.stations.append(StationConfig(
                name=s["name"],
                charging_current_entity=s["charging_current_entity"],
                charging_status_entity=s["charging_status_entity"],
                charge_rate_entity=s["charge_rate_entity"],
                override_state_entity=s["override_state_entity"],
                vehicle_connected_entity=s["vehicle_connected_entity"],
            ))

    if options.get("enable_charging_entity"):
        config.enable_charging_entity = options["enable_charging_entity"]
    if options.get("mode_entity"):
        config.mode_entity = options["mode_entity"]
    if options.get("pv_sensor_entity_id"):
        config.pv_sensor_entity_id = options["pv_sensor_entity_id"]
    if options.get("total_current_limit"):
        config.total_current_limit = int(options["total_current_limit"])
    if options.get("voltage"):
        config.voltage = int(options["voltage"])
    if options.get("phases"):
        config.phases = int(options["phases"])
    if options.get("hysteresis_threshold") is not None:
        config.hysteresis_threshold = float(options["hysteresis_threshold"])
    if options.get("hysteresis_delay") is not None:
        config.hysteresis_delay = float(options["hysteresis_delay"])
    if options.get("ramp_up_delay") is not None:
        config.ramp_up_delay = float(options["ramp_up_delay"])
    if options.get("measurement_interval") is not None:
        config.measurement_interval = float(options["measurement_interval"])
