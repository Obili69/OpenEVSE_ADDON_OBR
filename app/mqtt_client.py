"""MQTT client wrapper with auto-reconnect for aiomqtt."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import aiomqtt

from .config import AppConfig
from .const import MQTT_RECONNECT_DELAY

logger = logging.getLogger(__name__)

# Type for MQTT message handler callbacks
MessageHandler = Callable[[str, str], Coroutine[Any, Any, None]]


class MQTTClient:
    """Async MQTT client with auto-reconnect and topic-based callback dispatch."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._subscriptions: dict[str, MessageHandler] = {}
        self._connected = asyncio.Event()
        self._client: aiomqtt.Client | None = None
        self._publish_queue: asyncio.Queue[tuple[str, str, bool]] = asyncio.Queue()

    @property
    def connected(self) -> asyncio.Event:
        """Event that is set when MQTT is connected."""
        return self._connected

    def register(self, topic: str, callback: MessageHandler) -> None:
        """Register a callback for a topic pattern.

        Args:
            topic: MQTT topic (supports + and # wildcards).
            callback: Async function(topic_str, payload_str) called on match.
        """
        self._subscriptions[topic] = callback
        logger.debug("Registered handler for topic: %s", topic)

    async def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        """Publish a message. Queues if not connected."""
        if self._client is not None and self._connected.is_set():
            try:
                await self._client.publish(topic, payload, retain=retain)
                return
            except aiomqtt.MqttError:
                logger.warning("Publish failed, queueing: %s", topic)
        self._publish_queue.put_nowait((topic, payload, retain))

    async def start(self) -> None:
        """Connect to MQTT broker and run the message dispatch loop.

        Auto-reconnects on connection loss.
        """
        while True:
            try:
                logger.info(
                    "Connecting to MQTT broker at %s:%d",
                    self._config.mqtt_host,
                    self._config.mqtt_port,
                )
                async with aiomqtt.Client(
                    hostname=self._config.mqtt_host,
                    port=self._config.mqtt_port,
                    username=self._config.mqtt_username or None,
                    password=self._config.mqtt_password or None,
                ) as client:
                    self._client = client
                    self._connected.set()
                    logger.info("MQTT connected")

                    # Subscribe to all registered topics
                    for topic in self._subscriptions:
                        await client.subscribe(topic)
                        logger.debug("Subscribed to: %s", topic)

                    # Drain publish queue
                    await self._drain_queue()

                    # Message dispatch loop
                    async for message in client.messages:
                        topic_str = str(message.topic)
                        payload_str = (
                            message.payload.decode("utf-8")
                            if isinstance(message.payload, (bytes, bytearray))
                            else str(message.payload)
                        )
                        await self._dispatch(topic_str, payload_str)

            except aiomqtt.MqttError as e:
                self._connected.clear()
                self._client = None
                logger.warning(
                    "MQTT connection lost: %s. Reconnecting in %ds...",
                    e,
                    MQTT_RECONNECT_DELAY,
                )
                await asyncio.sleep(MQTT_RECONNECT_DELAY)

    async def _drain_queue(self) -> None:
        """Publish all queued messages."""
        while not self._publish_queue.empty():
            topic, payload, retain = self._publish_queue.get_nowait()
            try:
                if self._client:
                    await self._client.publish(topic, payload, retain=retain)
            except aiomqtt.MqttError:
                # Re-queue on failure
                self._publish_queue.put_nowait((topic, payload, retain))
                break

    async def _dispatch(self, topic: str, payload: str) -> None:
        """Dispatch a received message to matching handlers."""
        for pattern, handler in self._subscriptions.items():
            if self._topic_matches(pattern, topic):
                try:
                    await handler(topic, payload)
                except Exception:
                    logger.exception(
                        "Error in handler for topic %s (pattern %s)",
                        topic,
                        pattern,
                    )

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        """Check if an MQTT topic matches a subscription pattern.

        Supports + (single level) and # (multi level) wildcards.
        """
        pattern_parts = pattern.split("/")
        topic_parts = topic.split("/")

        for i, pat in enumerate(pattern_parts):
            if pat == "#":
                return True
            if i >= len(topic_parts):
                return False
            if pat != "+" and pat != topic_parts[i]:
                return False

        return len(pattern_parts) == len(topic_parts)
