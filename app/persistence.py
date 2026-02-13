"""Persistence: save and load state across restarts."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .const import STATE_FILE

logger = logging.getLogger(__name__)


class Persistence:
    """Manages persistent state storage in /data/state.json."""

    def __init__(self, path: str = STATE_FILE) -> None:
        self._path = path

    def save(self, state: dict[str, Any]) -> None:
        """Save state to disk.

        Args:
            state: Dictionary with keys like 'mode', 'allocations',
                   'hysteresis_threshold', 'ramp_up_delay'.
        """
        try:
            # Write to temp file first, then rename for atomicity
            tmp_path = self._path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, self._path)
            logger.debug("State saved to %s", self._path)
        except OSError as e:
            logger.warning("Failed to save state: %s", e)

    def load(self) -> dict[str, Any] | None:
        """Load state from disk.

        Returns:
            State dictionary, or None if file doesn't exist or is corrupt.
        """
        if not os.path.exists(self._path):
            logger.info("No persisted state found at %s", self._path)
            return None

        try:
            with open(self._path) as f:
                state = json.load(f)
            logger.info("Loaded persisted state from %s", self._path)
            return state
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load state from %s: %s", self._path, e)
            return None
