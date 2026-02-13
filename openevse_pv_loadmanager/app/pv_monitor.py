"""PV Monitor: solar power tracking and cloud detection."""

from __future__ import annotations

import logging
import statistics
import time

from .config import AppConfig
from .const import (
    CLOUD_DETECTION_VARIANCE_THRESHOLD,
    CLOUD_DETECTION_WINDOW,
    PV_STALE_TIMEOUT,
)
from .models import PVData, PVSample
from .mqtt_client import MQTTClient

logger = logging.getLogger(__name__)


class PVMonitor:
    """Monitors PV grid export power and detects cloud transients."""

    def __init__(self, config: AppConfig, mqtt: MQTTClient) -> None:
        self._config = config
        self._mqtt = mqtt
        self.data = PVData()

    def setup_subscriptions(self) -> None:
        """Register MQTT subscription for grid export power."""
        self._mqtt.register(
            self._config.pv_grid_export_topic,
            self._on_grid_export,
        )

    async def _on_grid_export(self, topic: str, payload: str) -> None:
        """Handle grid export power update.

        Positive value = exporting to grid (surplus available).
        Negative value = importing from grid (no surplus).
        """
        try:
            power_w = float(payload)
        except ValueError:
            logger.warning("Invalid grid export power value: %s", payload)
            return

        now = time.time()
        self.data.grid_export_power_w = power_w
        self.data.last_update = now

        # Add to history for cloud detection
        self.data.history.append(PVSample(value=power_w, timestamp=now))

        # Trim old samples
        cutoff = now - CLOUD_DETECTION_WINDOW
        self.data.history = [s for s in self.data.history if s.timestamp > cutoff]

    def get_available_current(self) -> float:
        """Get available PV surplus as current in amperes.

        Returns 0 if PV data is stale or no surplus available.
        """
        if self.is_stale():
            logger.warning("PV data stale (>%ds), returning 0A", PV_STALE_TIMEOUT)
            return 0.0

        if self.is_cloud_detected():
            return self.get_conservative_current()

        # Positive export = surplus available
        surplus_w = max(0.0, self.data.grid_export_power_w)
        return surplus_w / self._config.voltage

    def is_stale(self) -> bool:
        """Check if PV data is too old to be reliable."""
        if self.data.last_update == 0:
            return True
        return (time.time() - self.data.last_update) > PV_STALE_TIMEOUT

    def is_cloud_detected(self) -> bool:
        """Detect fast PV fluctuations indicating cloud cover.

        Uses variance of recent power readings over the detection window.
        """
        if len(self.data.history) < 3:
            return False

        values = [s.value for s in self.data.history]
        try:
            variance = statistics.variance(values)
        except statistics.StatisticsError:
            return False

        detected = variance > CLOUD_DETECTION_VARIANCE_THRESHOLD
        if detected:
            logger.debug("Cloud detected: variance=%.0f (threshold=%d)", variance, CLOUD_DETECTION_VARIANCE_THRESHOLD)
        return detected

    def get_conservative_current(self) -> float:
        """Get conservative current estimate during cloud conditions.

        Uses the minimum of recent readings to avoid over-allocation
        during rapid PV fluctuations.
        """
        if not self.data.history:
            return 0.0

        min_power = min(s.value for s in self.data.history)
        # Only use surplus (positive values)
        surplus_w = max(0.0, min_power)
        current = surplus_w / self._config.voltage

        logger.debug(
            "Cloud mode: using conservative %.1fA (min %.0fW of %d samples)",
            current,
            min_power,
            len(self.data.history),
        )
        return current
