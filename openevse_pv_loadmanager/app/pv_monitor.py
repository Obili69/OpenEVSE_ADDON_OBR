"""PV Monitor: solar power tracking via HA Supervisor API and cloud detection."""

from __future__ import annotations

import logging
import os
import statistics
import time

import aiohttp

from .config import AppConfig
from .const import (
    CLOUD_DETECTION_VARIANCE_THRESHOLD,
    CLOUD_DETECTION_WINDOW,
    HA_SUPERVISOR_API_URL,
    PV_STALE_TIMEOUT,
)
from .models import PVData, PVSample

logger = logging.getLogger(__name__)


class PVMonitor:
    """Monitors PV power by polling a HA sensor via the Supervisor API."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._entity_id = config.pv_sensor_entity_id
        self._supervisor_token = os.environ.get("SUPERVISOR_TOKEN", "")
        self.data = PVData()

        if not self._supervisor_token:
            logger.warning("SUPERVISOR_TOKEN not set - HA API access will fail")

    async def poll(self) -> None:
        """Poll the HA sensor for current grid import power.

        grid_import_power interpretation:
        - Positive = importing from grid (no surplus)
        - Negative = exporting to grid (surplus available)

        Surplus watts = abs(min(0, import_value))
        """
        url = f"{HA_SUPERVISOR_API_URL}/states/{self._entity_id}"
        headers = {
            "Authorization": f"Bearer {self._supervisor_token}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "HA API returned %d for %s", resp.status, self._entity_id
                        )
                        return

                    data = await resp.json()
                    state_value = data.get("state")

                    if state_value in ("unavailable", "unknown", None):
                        logger.warning("Sensor %s is %s", self._entity_id, state_value)
                        return

                    import_power_w = float(state_value)

        except (aiohttp.ClientError, TimeoutError) as e:
            logger.warning("HA API request failed: %s", e)
            return
        except (ValueError, TypeError) as e:
            logger.warning("Invalid sensor value from %s: %s", self._entity_id, e)
            return

        now = time.time()

        # Convert import to surplus: negative import = export = surplus
        surplus_w = abs(min(0.0, import_power_w))
        self.data.grid_export_power_w = surplus_w
        self.data.last_update = now

        # Add to history for cloud detection
        self.data.history.append(PVSample(value=surplus_w, timestamp=now))

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

        return self.data.grid_export_power_w / self._config.voltage

    def is_stale(self) -> bool:
        """Check if PV data is too old to be reliable."""
        if self.data.last_update == 0:
            return True
        return (time.time() - self.data.last_update) > PV_STALE_TIMEOUT

    def is_cloud_detected(self) -> bool:
        """Detect fast PV fluctuations indicating cloud cover."""
        if len(self.data.history) < 3:
            return False

        values = [s.value for s in self.data.history]
        try:
            variance = statistics.variance(values)
        except statistics.StatisticsError:
            return False

        detected = variance > CLOUD_DETECTION_VARIANCE_THRESHOLD
        if detected:
            logger.debug(
                "Cloud detected: variance=%.0f (threshold=%d)",
                variance,
                CLOUD_DETECTION_VARIANCE_THRESHOLD,
            )
        return detected

    def get_conservative_current(self) -> float:
        """Get conservative current estimate during cloud conditions."""
        if not self.data.history:
            return 0.0

        min_surplus = min(s.value for s in self.data.history)
        current = max(0.0, min_surplus) / self._config.voltage

        logger.debug(
            "Cloud mode: conservative %.1fA (min %.0fW of %d samples)",
            current,
            min_surplus,
            len(self.data.history),
        )
        return current
