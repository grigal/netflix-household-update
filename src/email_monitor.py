"""Async IMAP email monitoring with IDLE support."""

import asyncio
from typing import AsyncIterator, Optional

import aioimaplib
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings
from .parsers import NetflixEmailProcessor

logger = structlog.get_logger(__name__)


class EmailMonitor:
    """Async IMAP email monitor with IDLE support."""

    def __init__(self, settings: Settings):
        """Initialize email monitor.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.client: Optional[aioimaplib.IMAP4_SSL] = None
        self.email_processor = NetflixEmailProcessor(
            sender_emails=settings.sender_emails,
            link_patterns=settings.netflix_link_patterns,
        )
        self._running = False

    async def connect(self) -> None:
        """Connect to IMAP server with retry logic."""
        await self._connect_with_retry()

    @retry(
        retry=retry_if_exception_type((aioimaplib.AioImapException, ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _connect_with_retry(self) -> None:
        """Connect to IMAP server with exponential backoff retry."""
        try:
            logger.info(
                "connecting_to_imap",
                server=self.settings.imap_server,
                port=self.settings.imap_port,
            )

            self.client = aioimaplib.IMAP4_SSL(
                host=self.settings.imap_server,
                port=self.settings.imap_port,
            )

            await self.client.wait_hello_from_server()

            # Login
            result = await self.client.login(
                self.settings.imap_user,
                self.settings.get_imap_password(),
            )

            if result.result != "OK":
                raise aioimaplib.AioImapException(f"Login failed: {result}")

            # Select mailbox
            result = await self.client.select(self.settings.mailbox_name)

            if result.result != "OK":
                raise aioimaplib.AioImapException(f"Mailbox selection failed: {result}")

            # Create Netflix folder if needed
            if self.settings.move_emails_to_mailbox:
                await self.client.create(self.settings.move_to_mailbox_name)

            logger.info("imap_connected", mailbox=self.settings.mailbox_name)

        except Exception as e:
            logger.error("imap_connection_failed", error=str(e), exc_info=True)
            raise

    async def disconnect(self) -> None:
        """Disconnect from IMAP server."""
        if self.client:
            try:
                await self.client.logout()
                logger.info("imap_disconnected")
            except Exception as e:
                logger.warning("imap_disconnect_error", error=str(e))
            finally:
                self.client = None

    async def fetch_unread_emails(self) -> AsyncIterator[tuple[bytes, bytes]]:
        """Fetch unread emails from Netflix.

        Yields:
            Tuple of (email_id, raw_email_data)
        """
        if not self.client:
            raise RuntimeError("IMAP client not connected")

        # Search for unread emails from Netflix
        # TODO: Temporarily accepting tomas.grigal@gmail.com for testing
        search_criteria = 'UNSEEN (OR FROM "Netflix" FROM "tomas.grigal@gmail.com")'
        result = await self.client.search(search_criteria)

        if result.result != "OK":
            logger.warning("email_search_failed", result=result)
            return

        # Parse email IDs
        email_ids = result.lines[0].split() if result.lines else []

        if not email_ids:
            logger.debug("no_unread_emails")
            return

        logger.info("found_unread_emails", count=len(email_ids))

        # Fetch each email
        for email_id in email_ids:
            try:
                # Convert bytes to string if needed
                email_id_str = email_id.decode() if isinstance(email_id, bytes) else email_id
                result = await self.client.fetch(email_id_str, "(RFC822)")

                if result.result != "OK":
                    logger.warning("email_fetch_failed", email_id=email_id, result=str(result))
                    continue

                # Extract raw email from response
                # Response format: [b'1 FETCH (RFC822 {size}', b'raw email data...', b')']
                # The RFC822 data is typically in the second element
                raw_email = None

                # Log the response structure for debugging
                logger.debug("fetch_response_debug",
                           email_id=email_id,
                           result_lines_count=len(result.lines),
                           first_few_lines=[str(line[:100]) for line in result.lines[:3]])

                # aioimaplib FETCH response structure:
                # result.lines[0]: b'ID FETCH (RFC822 {size}'
                # result.lines[1]: bytearray or bytes with actual email data
                # result.lines[2+]: additional data and closing paren
                if len(result.lines) >= 2:
                    # The actual email data is usually in index 1
                    raw_email = result.lines[1]

                    # Convert bytearray to bytes if needed
                    if isinstance(raw_email, bytearray):
                        raw_email = bytes(raw_email)

                if raw_email and isinstance(raw_email, bytes):
                    yield (email_id, raw_email)
                else:
                    logger.warning("email_data_not_found",
                                 email_id=email_id,
                                 lines_count=len(result.lines),
                                 raw_email_type=str(type(raw_email)) if raw_email else "None")

            except Exception as e:
                logger.error(
                    "email_fetch_exception",
                    email_id=email_id,
                    error=str(e),
                    exc_info=True,
                )

    async def move_email_to_folder(self, email_id: bytes) -> None:
        """Move email to processed folder and mark as deleted.

        Args:
            email_id: Email ID to move
        """
        if not self.client:
            raise RuntimeError("IMAP client not connected")

        if not self.settings.move_emails_to_mailbox:
            return

        try:
            # Convert bytes to string if needed
            email_id_str = email_id.decode() if isinstance(email_id, bytes) else email_id

            # Copy to Netflix folder
            await self.client.copy(email_id_str, self.settings.move_to_mailbox_name)

            # Mark as deleted
            await self.client.store(email_id_str, "+FLAGS", r"(\Deleted)")

            logger.debug("email_moved", email_id=email_id)

        except Exception as e:
            logger.error(
                "email_move_failed",
                email_id=email_id,
                error=str(e),
                exc_info=True,
            )

    async def expunge_deleted(self) -> None:
        """Permanently remove emails marked as deleted."""
        if not self.client:
            raise RuntimeError("IMAP client not connected")

        if self.settings.move_emails_to_mailbox:
            try:
                await self.client.expunge()
                logger.debug("mailbox_expunged")
            except Exception as e:
                logger.warning("expunge_failed", error=str(e))

    async def wait_for_new_emails_idle(self, timeout: int = 1740) -> bool:
        """Wait for new emails using IMAP IDLE (push notifications).

        Args:
            timeout: IDLE timeout in seconds (default 29 minutes, RFC recommends < 30min)

        Returns:
            True if new emails arrived, False if timeout or error
        """
        if not self.client:
            raise RuntimeError("IMAP client not connected")

        try:
            # Check if server supports IDLE
            if not hasattr(self.client, "idle_start"):
                logger.warning("imap_idle_not_supported")
                return False

            logger.debug("entering_idle_mode", timeout=timeout)

            # Enter IDLE mode
            await self.client.idle_start(timeout=timeout)

            # Wait for notification or timeout
            result = await self.client.wait_server_push(timeout=timeout)

            # Exit IDLE mode (not async)
            self.client.idle_done()

            # Log what we received
            logger.info("idle_received_response", result=str(result))

            # Check if we got new mail notification
            # result can be a list of bytes or a Response object
            lines_to_check = []
            if isinstance(result, list):
                lines_to_check = result
            elif hasattr(result, 'lines'):
                lines_to_check = result.lines

            if lines_to_check:
                logger.info("idle_response_lines", lines=[str(line) for line in lines_to_check])
                for line in lines_to_check:
                    if b"EXISTS" in line:
                        logger.info("new_email_notification_received")
                        return True

            logger.info("idle_timeout_no_new_emails")
            return False

        except asyncio.TimeoutError:
            # Normal timeout - no emails arrived during IDLE period
            logger.debug("idle_timeout_expired")
            return False
        except Exception as e:
            # Actual errors (connection issues, protocol errors, etc.)
            logger.warning("idle_mode_failed",
                          error=str(e),
                          error_type=type(e).__name__,
                          exc_info=True)
            return False

    async def process_emails(self) -> list[str]:
        """Process all unread Netflix emails.

        Returns:
            List of verification links extracted
        """
        verification_links = []

        async for email_id, raw_email in self.fetch_unread_emails():
            try:
                # Extract verification link
                link = self.email_processor.process_email(raw_email)

                if link:
                    verification_links.append(link)
                    logger.info("verification_link_found", link=link)

                # Move email to processed folder
                await self.move_email_to_folder(email_id)

            except Exception as e:
                logger.error(
                    "email_processing_failed",
                    email_id=email_id,
                    error=str(e),
                    exc_info=True,
                )

        # Clean up deleted emails
        await self.expunge_deleted()

        return verification_links

    async def monitor_with_idle(self) -> AsyncIterator[list[str]]:
        """Monitor emails using IMAP IDLE (most efficient).

        Yields:
            List of verification links when new emails arrive
        """
        self._running = True
        logger.info("starting_idle_monitoring")

        while self._running:
            try:
                # Wait for new emails
                new_emails = await self.wait_for_new_emails_idle()

                if new_emails:
                    # Process new emails
                    links = await self.process_emails()
                    if links:
                        yield links

            except Exception as e:
                logger.error("idle_monitoring_error", error=str(e), exc_info=True)
                # Reconnect on error
                await self.disconnect()
                await asyncio.sleep(5)
                await self.connect()

    async def monitor_with_polling(self) -> AsyncIterator[list[str]]:
        """Monitor emails using polling (fallback if IDLE not supported).

        Yields:
            List of verification links when found
        """
        self._running = True
        logger.info(
            "starting_polling_monitoring",
            interval=self.settings.polling_time_in_seconds,
        )

        while self._running:
            try:
                # Check for new emails
                links = await self.process_emails()

                if links:
                    yield links

                # Wait before next poll
                await asyncio.sleep(self.settings.polling_time_in_seconds)

            except Exception as e:
                logger.error("polling_monitoring_error", error=str(e), exc_info=True)
                # Reconnect on error
                await self.disconnect()
                await asyncio.sleep(5)
                await self.connect()

    def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        logger.info("stopping_email_monitor")
