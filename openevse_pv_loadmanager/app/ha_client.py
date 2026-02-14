"""Home Assistant Supervisor API client."""

from __future__ import annotations

import logging
import os

import aiohttp

from .const import HA_API_SERVICES, HA_API_STATES

logger = logging.getLogger(__name__)


class HAClient:
    """Client for the HA Supervisor REST API."""

    def __init__(self) -> None:
        self._token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not self._token:
            logger.warning("SUPERVISOR_TOKEN not set - HA API calls will fail")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def get_state(self, entity_id: str) -> str | None:
        """Get the state value of an entity.

        Returns the state string, or None on error.
        """
        url = HA_API_STATES.format(entity_id)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=self._headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        logger.warning("GET %s returned %d", entity_id, resp.status)
                        return None
                    data = await resp.json()
                    state = data.get("state")
                    if state in ("unavailable", "unknown"):
                        logger.debug("Entity %s is %s", entity_id, state)
                        return None
                    return state
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.warning("Failed to get %s: %s", entity_id, e)
            return None

    async def get_float(self, entity_id: str) -> float | None:
        """Get entity state as a float."""
        state = await self.get_state(entity_id)
        if state is None:
            return None
        try:
            return float(state)
        except (ValueError, TypeError):
            logger.warning("Entity %s has non-numeric state: %s", entity_id, state)
            return None

    async def call_service(
        self, domain: str, service: str, data: dict
    ) -> bool:
        """Call a HA service.

        Returns True on success.
        """
        url = HA_API_SERVICES.format(domain, service)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=self._headers, json=data,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status not in (200, 201):
                        logger.warning(
                            "Service %s.%s returned %d", domain, service, resp.status
                        )
                        return False
                    return True
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.warning("Service call %s.%s failed: %s", domain, service, e)
            return False

    async def set_number(self, entity_id: str, value: float) -> bool:
        """Set a number entity value."""
        return await self.call_service(
            "number", "set_value",
            {"entity_id": entity_id, "value": round(value)},
        )

    async def set_select(self, entity_id: str, option: str) -> bool:
        """Set a select entity option."""
        return await self.call_service(
            "select", "select_option",
            {"entity_id": entity_id, "option": option},
        )
