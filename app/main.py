"""Entry point for the OpenEVSE PV Load Manager."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .config import load_config
from .evse_manager import EVSEManager
from .ha_discovery import HADiscoveryPublisher
from .load_manager import LoadManager
from .mqtt_client import MQTTClient
from .persistence import Persistence
from .pv_monitor import PVMonitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Run the PV Load Manager."""
    logger.info("Starting OpenEVSE PV Load Manager")

    config = load_config()
    logger.info(
        "Config: %d stations, %dA limit, mode=%s, interval=%ds",
        len(config.evse_topics),
        config.total_current_limit,
        config.initial_mode,
        config.measurement_interval,
    )

    # Initialize components
    mqtt = MQTTClient(config)
    persistence = Persistence()
    evse = EVSEManager(config, mqtt)
    pv = PVMonitor(config, mqtt)
    lm = LoadManager(config, evse, pv, mqtt, persistence)
    discovery = HADiscoveryPublisher(config, mqtt)

    # Restore persisted state
    saved = persistence.load()
    if saved:
        lm.restore_state(saved)
        logger.info("Restored persisted state: mode=%s", saved.get("mode"))

    # Setup MQTT subscriptions
    evse.setup_subscriptions()
    pv.setup_subscriptions()
    lm.setup_subscriptions()

    # Shutdown handler
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    async def shutdown_watcher() -> None:
        await shutdown_event.wait()
        logger.info("Shutting down: clearing overrides")
        await evse.clear_all_overrides()
        await mqtt.publish("loadmanager/status", "offline", retain=True)
        # Allow messages to be sent
        await asyncio.sleep(1)
        # Cancel all tasks
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

    # Run all tasks
    try:
        await asyncio.gather(
            mqtt.start(),
            lm.run(),
            discovery.publish_on_connect(mqtt),
            shutdown_watcher(),
        )
    except asyncio.CancelledError:
        logger.info("Tasks cancelled, exiting")
    except Exception:
        logger.exception("Unexpected error in main loop")
    finally:
        logger.info("OpenEVSE PV Load Manager stopped")


if __name__ == "__main__":
    asyncio.run(main())
