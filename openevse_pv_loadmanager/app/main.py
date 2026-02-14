"""Entry point for the OpenEVSE PV Load Manager."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .config import load_config
from .ha_client import HAClient
from .load_manager import LoadManager
from .persistence import Persistence

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
        "Config: %d stations, %dA limit, interval=%ds",
        len(config.stations),
        config.total_current_limit,
        config.measurement_interval,
    )

    # Initialize components
    ha = HAClient()
    persistence = Persistence()
    lm = LoadManager(config, ha, persistence)

    # Restore persisted state
    saved = persistence.load()
    if saved:
        lm.restore_state(saved)
        logger.info("Restored persisted state: mode=%s", saved.get("mode"))

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
        await lm.clear_all_overrides()
        await asyncio.sleep(1)
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

    # Run
    try:
        await asyncio.gather(
            lm.run(),
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
