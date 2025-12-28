"""Main application entry point."""

import asyncio
import signal
import sys
import time
from typing import Optional

import structlog

from .browser import BrowserPool
from .config import Settings, load_settings
from .email_monitor import EmailMonitor
from .metrics import get_metrics
from .protocols import EmailNotificationProvider, EmailProcessor, VerificationHandler
from .timing_report import TimingReportProcessor

logger = structlog.get_logger(__name__)


class NetflixHouseholdUpdater:
    """Main application orchestrator."""

    def __init__(
        self,
        settings: Settings,
        email_monitor: Optional[EmailNotificationProvider | EmailProcessor] = None,
        browser_pool: Optional[VerificationHandler] = None,
    ):
        """Initialize application with dependency injection.

        Args:
            settings: Application settings
            email_monitor: Email monitoring component (optional, creates default if None)
            browser_pool: Browser verification component (optional, creates default if None)
        """
        self.settings = settings
        self.email_monitor = email_monitor or EmailMonitor(settings)
        self.browser_pool = browser_pool or BrowserPool(settings, pool_size=1)
        self._shutdown_event = asyncio.Event()
        # Two-queue architecture for maximum parallelism
        self._email_queue: asyncio.Queue[int] = asyncio.Queue()
        self._link_queue: asyncio.Queue[str] = asyncio.Queue()

    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("initializing_application")

        await self.browser_pool.initialize()
        await self.email_monitor.connect()

        logger.info("application_initialized")

    async def cleanup(self) -> None:
        """Clean up all resources."""
        logger.info("cleaning_up_application")

        self.email_monitor.stop()
        await self.email_monitor.disconnect()
        await self.browser_pool.cleanup()

        logger.info("application_cleaned_up")

    async def _email_monitoring_loop(self) -> None:
        """Continuously monitor for new email notifications.

        This loop stays in IDLE mode as much as possible, detecting
        new emails and queuing their IDs for processing without waiting.
        """
        logger.info("starting_email_monitoring_loop")
        metrics = get_metrics()
        idle_enter_time = time.time()

        try:
            async for email_id in self.email_monitor.monitor_idle_notifications():
                if self._shutdown_event.is_set():
                    break

                # Track IDLE pause duration
                idle_exit_time = time.time()
                idle_pause = idle_exit_time - idle_enter_time
                metrics.record_idle_pause(idle_pause)
                metrics.idle_detections += 1

                # Queue the email ID for processing (non-blocking)
                notification_timestamp = time.time()
                logger.info("email_notification_received",
                           email_id=email_id,
                           notification_timestamp=notification_timestamp,
                           idle_pause_seconds=round(idle_pause, 3))
                await self._email_queue.put(email_id)

                # Track queue depth
                metrics.record_queue_depth("email", self._email_queue.qsize())

                # Reset idle timer for next iteration
                idle_enter_time = time.time()

        except asyncio.CancelledError:
            logger.info("email_monitoring_cancelled")
        except Exception as e:
            logger.error("email_monitoring_error", error=str(e), exc_info=True)
            raise

    async def _email_processing_loop(self) -> None:
        """Continuously process emails from the email queue.

        This loop fetches emails by ID, extracts verification links,
        and queues them for verification without blocking.
        """
        logger.info("starting_email_processing_loop")
        metrics = get_metrics()

        try:
            while not self._shutdown_event.is_set():
                try:
                    # Wait for email ID from monitoring loop
                    email_id = await asyncio.wait_for(
                        self._email_queue.get(),
                        timeout=5.0
                    )

                    logger.info("processing_email_by_id", email_id=email_id)
                    start_time = time.time()

                    # Fetch and process the email
                    link = await self.email_monitor.process_email_by_id(email_id)

                    # Track timing
                    duration = time.time() - start_time
                    metrics.record_email_fetch(duration)

                    if link:
                        # Queue the verification link
                        await self._link_queue.put(link)
                        logger.info("link_extracted_from_email",
                                   email_id=email_id,
                                   link=link,
                                   email_processing_seconds=round(duration, 2))

                        # Track link queue depth
                        metrics.record_queue_depth("link", self._link_queue.qsize())
                    else:
                        logger.info("email_processing_completed",
                                   email_id=email_id,
                                   duration_seconds=round(duration, 2),
                                   link_found=False)

                    self._email_queue.task_done()

                except asyncio.TimeoutError:
                    # No emails in queue, continue waiting
                    continue

        except asyncio.CancelledError:
            logger.info("email_processing_cancelled")
        except Exception as e:
            logger.error("email_processing_error", error=str(e), exc_info=True)
            raise

    async def _link_processing_loop(self) -> None:
        """Continuously process verification links from the link queue.

        This loop handles browser automation for Netflix verification
        independently of email processing.
        """
        logger.info("starting_link_processing_loop")
        metrics = get_metrics()

        try:
            while not self._shutdown_event.is_set():
                try:
                    # Wait for verification link from email processing loop
                    link = await asyncio.wait_for(
                        self._link_queue.get(),
                        timeout=5.0
                    )

                    logger.info("processing_verification_link", link=link)
                    start_time = time.time()
                    success = False

                    try:
                        success = await self.browser_pool.process_link(link)
                    except Exception as e:
                        logger.error("link_processing_failed", link=link, error=str(e), exc_info=True)

                    # Track timing and result
                    duration = time.time() - start_time
                    verification_timestamp = time.time()
                    metrics.record_verification(duration, success)
                    logger.info("end_to_end_verification_completed",
                               link=link,
                               verification_timestamp=verification_timestamp,
                               verification_seconds=round(duration, 2),
                               success=success)

                    self._link_queue.task_done()

                except asyncio.TimeoutError:
                    # No links in queue, continue waiting
                    continue

        except asyncio.CancelledError:
            logger.info("link_processing_cancelled")
        except Exception as e:
            logger.error("link_processing_error", error=str(e), exc_info=True)
            raise

    async def run_with_idle(self, link_workers: int = 1) -> None:
        """Run application using IMAP IDLE with dual-queue concurrent processing.

        Args:
            link_workers: Number of concurrent link processing workers (default: 1)

        Runs multiple independent loops:
        1. Email monitoring - stays in IDLE, detects new emails instantly
        2. Email processing - fetches emails by ID, extracts links
        3. Link processing - handles browser verification (configurable workers)

        This two-queue architecture allows:
        - IDLE mode stays active (max email detection speed)
        - Email processing doesn't block link verification
        - Multiple link workers enable parallel verification
        """
        logger.info("starting_application_with_idle")
        logger.info("architecture", mode="dual_queue_concurrent_processing",
                   email_queue_workers=1, link_queue_workers=link_workers)

        try:
            workers = [
                self._email_monitoring_loop(),
                self._email_processing_loop(),
            ]

            # Add configurable number of link processing workers
            for i in range(link_workers):
                workers.append(self._link_processing_loop())
                logger.debug("started_link_worker", worker_id=i+1)

            # Run all workers concurrently
            await asyncio.gather(*workers)

        except asyncio.CancelledError:
            logger.info("application_cancelled")
        except Exception as e:
            logger.error("application_error", error=str(e), exc_info=True)
            raise
        finally:
            # Print performance metrics
            metrics = get_metrics()
            metrics.print_summary()
            metrics.log_summary()

    async def run(self) -> None:
        """Run application using IDLE mode with dual-queue architecture."""
        await self.initialize()

        try:
            logger.info("using_imap_idle_mode")
            await self.run_with_idle()

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
            TimingReportProcessor(),  # Auto-generate timing reports from logs
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

    settings = load_settings()
    setup_logging(settings)

    logger.info(
        "netflix_household_updater_starting",
        version="2.0.0",
        imap_server=settings.imap_server,
        mailbox=settings.mailbox_name,
    )

    app = NetflixHouseholdUpdater(settings)
    setup_signal_handlers(app)

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
