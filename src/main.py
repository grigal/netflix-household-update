"""Main application entry point."""

import asyncio
import signal
import sys
from typing import Optional

import structlog

from .browser import BrowserPool
from .config import Settings, load_settings
from .email_monitor import EmailMonitor

logger = structlog.get_logger(__name__)


class NetflixHouseholdUpdater:
    """Main application orchestrator."""

    def __init__(self, settings: Settings):
        """Initialize application.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.email_monitor = EmailMonitor(settings)
        self.browser_pool = BrowserPool(settings, pool_size=1)
        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("initializing_application")

        # Initialize browser pool
        await self.browser_pool.initialize()

        # Connect to email server
        await self.email_monitor.connect()

        logger.info("application_initialized")

    async def cleanup(self) -> None:
        """Clean up all resources."""
        logger.info("cleaning_up_application")

        # Stop email monitor
        self.email_monitor.stop()

        # Disconnect from email
        await self.email_monitor.disconnect()

        # Clean up browsers
        await self.browser_pool.cleanup()

        logger.info("application_cleaned_up")

    async def process_verification_links(self, links: list[str]) -> None:
        """Process verification links concurrently.

        Args:
            links: List of verification URLs
        """
        if not links:
            return

        logger.info("processing_verification_links", count=len(links))

        # Process links concurrently
        tasks = [self.browser_pool.process_link(link) for link in links]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log results
        success_count = sum(1 for r in results if r is True)
        failure_count = len(results) - success_count

        logger.info(
            "verification_links_processed",
            total=len(links),
            success=success_count,
            failed=failure_count,
        )

    async def run_with_idle(self) -> None:
        """Run application using IMAP IDLE (push notifications)."""
        logger.info("starting_application_with_idle")

        try:
            async for links in self.email_monitor.monitor_with_idle():
                if self._shutdown_event.is_set():
                    break

                await self.process_verification_links(links)

        except asyncio.CancelledError:
            logger.info("application_cancelled")
        except Exception as e:
            logger.error("application_error", error=str(e), exc_info=True)
            raise

    async def run_with_polling(self) -> None:
        """Run application using polling (fallback)."""
        logger.info(
            "starting_application_with_polling",
            interval=self.settings.polling_time_in_seconds,
        )

        try:
            async for links in self.email_monitor.monitor_with_polling():
                if self._shutdown_event.is_set():
                    break

                await self.process_verification_links(links)

        except asyncio.CancelledError:
            logger.info("application_cancelled")
        except Exception as e:
            logger.error("application_error", error=str(e), exc_info=True)
            raise

    async def run(self) -> None:
        """Run application with automatic IDLE/polling selection."""
        await self.initialize()

        try:
            # Try IDLE first, fall back to polling if not supported
            try:
                # Check if server supports IDLE
                if hasattr(self.email_monitor.client, "idle"):
                    logger.info("using_imap_idle_mode")
                    await self.run_with_idle()
                else:
                    logger.info("idle_not_supported_using_polling")
                    await self.run_with_polling()
            except Exception as e:
                logger.warning("idle_failed_falling_back_to_polling", error=str(e))
                # Reconnect and use polling
                await self.email_monitor.disconnect()
                await self.email_monitor.connect()
                await self.run_with_polling()

        finally:
            await self.cleanup()

    def shutdown(self) -> None:
        """Signal shutdown."""
        logger.info("shutdown_requested")
        self._shutdown_event.set()


def setup_logging(settings: Settings) -> None:
    """Configure structured logging.

    Args:
        settings: Application settings
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if sys.stderr.isatty() else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(settings.logging_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def setup_signal_handlers(app: NetflixHouseholdUpdater) -> None:
    """Setup signal handlers for graceful shutdown.

    Args:
        app: Application instance
    """

    def signal_handler(sig: int, frame: Optional[object]) -> None:
        """Handle shutdown signals."""
        logger.info("received_signal", signal=sig)
        app.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def async_main() -> None:
    """Async main entry point."""
    # Load settings
    settings = load_settings()

    # Setup logging
    setup_logging(settings)

    logger.info(
        "netflix_household_updater_starting",
        version="2.0.0",
        imap_server=settings.imap_server,
        mailbox=settings.mailbox_name,
    )

    # Create and run application
    app = NetflixHouseholdUpdater(settings)

    # Setup signal handlers
    setup_signal_handlers(app)

    # Run application
    try:
        await app.run()
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_received")
    except Exception as e:
        logger.critical("unhandled_exception", error=str(e), exc_info=True)
        sys.exit(1)

    logger.info("netflix_household_updater_stopped")


def main() -> None:
    """Main entry point for command-line execution."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass  # Already logged in async_main
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
