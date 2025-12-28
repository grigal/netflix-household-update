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
        self.idle_client: Optional[aioimaplib.IMAP4_SSL] = None
        self.command_client: Optional[aioimaplib.IMAP4_SSL] = None
        self.email_processor = NetflixEmailProcessor(
            sender_emails=settings.sender_emails,
            link_patterns=settings.netflix_link_patterns,
        )
        self._running = False

    async def connect(self) -> None:
        """Connect to IMAP server with retry logic."""
        await self._connect_idle_client()
        await self._connect_command_client()

    @retry(
        retry=retry_if_exception_type((aioimaplib.AioImapException, ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _connect_idle_client(self) -> None:
        """Connect IDLE client to IMAP server."""
        try:
            logger.info(
                "connecting_idle_client_to_imap",
                server=self.settings.imap_server,
                port=self.settings.imap_port,
            )

            self.idle_client = aioimaplib.IMAP4_SSL(
                host=self.settings.imap_server,
                port=self.settings.imap_port,
            )

            await self.idle_client.wait_hello_from_server()

            result = await self.idle_client.login(
                self.settings.imap_user,
                self.settings.get_imap_password(),
            )

            if result.result != "OK":
                raise aioimaplib.AioImapException(f"Idle client login failed: {result}")

            result = await self.idle_client.select(self.settings.mailbox_name)

            if result.result != "OK":
                raise aioimaplib.AioImapException(f"Idle client mailbox selection failed: {result}")

            logger.info("idle_client_connected", mailbox=self.settings.mailbox_name)

        except Exception as e:
            logger.error("idle_client_connection_failed", error=str(e), exc_info=True)
            raise

    @retry(
        retry=retry_if_exception_type((aioimaplib.AioImapException, ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _connect_command_client(self) -> None:
        """Connect command client to IMAP server."""
        try:
            logger.info(
                "connecting_command_client_to_imap",
                server=self.settings.imap_server,
                port=self.settings.imap_port,
            )

            self.command_client = aioimaplib.IMAP4_SSL(
                host=self.settings.imap_server,
                port=self.settings.imap_port,
            )

            await self.command_client.wait_hello_from_server()

            result = await self.command_client.login(
                self.settings.imap_user,
                self.settings.get_imap_password(),
            )

            if result.result != "OK":
                raise aioimaplib.AioImapException(f"Command client login failed: {result}")

            result = await self.command_client.select(self.settings.mailbox_name)

            if result.result != "OK":
                raise aioimaplib.AioImapException(f"Command client mailbox selection failed: {result}")

            if self.settings.move_emails_to_mailbox:
                await self.command_client.create(self.settings.move_to_mailbox_name)

            logger.info("command_client_connected", mailbox=self.settings.mailbox_name)

        except Exception as e:
            logger.error("command_client_connection_failed", error=str(e), exc_info=True)
            raise

    async def disconnect(self) -> None:
        """Disconnect from IMAP server."""
        if self.idle_client:
            try:
                await self.idle_client.logout()
                logger.info("idle_client_disconnected")
            except Exception as e:
                logger.warning("idle_client_disconnect_error", error=str(e))
            finally:
                self.idle_client = None

        if self.command_client:
            try:
                await self.command_client.logout()
                logger.info("command_client_disconnected")
            except Exception as e:
                logger.warning("command_client_disconnect_error", error=str(e))
            finally:
                self.command_client = None

    async def move_email_to_folder(self, email_id: str) -> None:
        """Mark email as read, move to processed folder, and mark as deleted.

        Args:
            email_id: Email ID to move
        """
        if not self.command_client:
            raise RuntimeError("IMAP command client not connected")

        try:
            await self.command_client.store(email_id, "+FLAGS", r"(\Seen)")

            if self.settings.move_emails_to_mailbox:
                await self.command_client.copy(email_id, self.settings.move_to_mailbox_name)
                await self.command_client.store(email_id, "+FLAGS", r"(\Deleted)")

            logger.debug("email_processed_and_moved", email_id=email_id)

        except Exception as e:
            logger.error(
                "email_move_failed",
                email_id=email_id,
                error=str(e),
                exc_info=True,
            )

    async def expunge_deleted(self) -> None:
        """Permanently remove emails marked as deleted."""
        if not self.command_client:
            raise RuntimeError("IMAP command client not connected")

        if self.settings.move_emails_to_mailbox:
            try:
                await self.command_client.expunge()
                logger.debug("mailbox_expunged")
            except Exception as e:
                logger.warning("expunge_failed", error=str(e))

    async def wait_for_new_emails_idle(self, timeout: int = 1740) -> Optional[str]:
        """Wait for new emails using IMAP IDLE (push notifications).

        Args:
            timeout: IDLE timeout in seconds (default 29 minutes, RFC recommends < 30min)

        Returns:
            Email ID if new email arrived, None if timeout or error
        """
        if not self.idle_client:
            raise RuntimeError("IMAP idle client not connected")

        try:
            if not hasattr(self.idle_client, "idle_start"):
                logger.warning("imap_idle_not_supported")
                return None

            logger.debug("entering_idle_mode", timeout=timeout)

            await self.idle_client.idle_start(timeout=timeout)

            result = await self.idle_client.wait_server_push(timeout=timeout)

            self.idle_client.idle_done()

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
                        # Extract email ID from "28382 EXISTS"
                        try:
                            email_id = line.split()[0].decode()
                            logger.info("new_email_notification_received", email_id=email_id)
                            return email_id
                        except (ValueError, IndexError) as e:
                            logger.warning("failed_to_parse_email_id", line=str(line), error=str(e))
                            return None

            logger.info("idle_timeout_no_new_emails")
            return None

        except asyncio.TimeoutError:
            # Normal timeout - no emails arrived during IDLE period
            logger.debug("idle_timeout_expired")
            return None
        except Exception as e:
            # Actual errors (connection issues, protocol errors, etc.)
            logger.warning("idle_mode_failed",
                          error=str(e),
                          error_type=type(e).__name__,
                          exc_info=True)
            return None

    async def fetch_email_by_id(self, email_id: str) -> Optional[tuple[str, bytes]]:
        """Fetch a specific email by ID.

        Args:
            email_id: IMAP email sequence number

        Returns:
            Tuple of (email_id, raw_email_data) or None if not found
        """
        if not self.command_client:
            raise RuntimeError("IMAP command client not connected")

        try:
            # Log the command client state
            logger.debug("command_client_state",
                       email_id=email_id,
                       has_protocol=hasattr(self.command_client, 'protocol'),
                       protocol_state=self.command_client.protocol.state if hasattr(self.command_client, 'protocol') else 'unknown')

            # CRITICAL FIX: EXISTS number (e.g., 28399) is NOT the actual sequence number!
            # EXISTS is a cumulative count including all deleted messages ever
            # The actual current messages have sequence numbers 1-N where N is much smaller
            # We need to fetch the LAST message using "*" which points to the highest sequence number

            logger.debug("exists_id_received", exists_number=email_id)

            # Use "*" to fetch the last (newest) message in the mailbox
            actual_email_id = "*"
            logger.info("corrected_email_id",
                       exists_number=email_id,
                       actual_sequence=actual_email_id,
                       reason="EXISTS_is_not_sequence_number")

            # Use BODY.PEEK[] to fetch without marking as read
            # Will only mark as read later if it's from Netflix
            # Note: Must use parentheses like (BODY.PEEK[]) for proper IMAP syntax
            logger.debug("attempting_body_peek_fetch", actual_email_id=actual_email_id)
            result = await self.command_client.fetch(actual_email_id, "(BODY.PEEK[])")

            # Detailed debug logging
            logger.debug("fetch_response_full_debug",
                       email_id=email_id,
                       result_status=result.result,
                       result_lines_count=len(result.lines),
                       all_lines=[str(line[:200]) for line in result.lines],
                       result_type=str(type(result)),
                       result_dir=[attr for attr in dir(result) if not attr.startswith('_')])

            if result.result != "OK":
                logger.warning("email_fetch_failed", email_id=email_id, result=str(result))
                return None

            # aioimaplib FETCH response structure:
            # result.lines[0]: b'ID FETCH (BODY[] {size}' or similar
            # result.lines[1]: bytearray or bytes with actual email data
            # But sometimes the response format is different - let's handle both

            # Check if we have data
            if len(result.lines) >= 2:
                raw_email = result.lines[1]

                # Convert bytearray to bytes if needed
                if isinstance(raw_email, bytearray):
                    raw_email = bytes(raw_email)

                return (email_id, raw_email)

            logger.warning("unexpected_fetch_response", email_id=email_id)
            return None

        except Exception as e:
            logger.error("fetch_email_by_id_failed", email_id=email_id, error=str(e), exc_info=True)
            return None

    async def process_email_by_id(self, email_id: str) -> Optional[str]:
        """Process a specific email by ID and extract verification link.

        Args:
            email_id: IMAP email sequence number

        Returns:
            Verification link if found, None otherwise
        """
        logger.info("processing_email_by_id", email_id=email_id)

        email_data = await self.fetch_email_by_id(email_id)
        if not email_data:
            logger.warning("email_not_found", email_id=email_id)
            return None

        _, raw_email = email_data

        try:
            link = self.email_processor.process_email(raw_email)

            if link:
                logger.info("verification_link_found", email_id=email_id, link=link)
                await self.move_email_to_folder(email_id)
                await self.expunge_deleted()
                return link
            else:
                logger.info("no_link_in_email", email_id=email_id)
                return None

        except Exception as e:
            logger.error("email_processing_failed", email_id=email_id, error=str(e), exc_info=True)
            return None

    async def monitor_idle_notifications(self) -> AsyncIterator[str]:
        """Monitor for new email notifications using IMAP IDLE.

        This method stays in IDLE mode as much as possible, only briefly
        exiting when a new email arrives. It does NOT process emails,
        just detects that they arrived and yields the email ID.

        Yields:
            Email ID when new emails are detected
        """
        self._running = True
        logger.info("starting_idle_notification_monitoring")

        while self._running:
            try:
                # Wait for new emails (IDLE active here - fast detection)
                email_id = await self.wait_for_new_emails_idle()

                if email_id:
                    # Yield the email ID for processing
                    yield email_id

            except Exception as e:
                logger.error("idle_monitoring_error", error=str(e), exc_info=True)
                # Reconnect on error
                await self.disconnect()
                await asyncio.sleep(5)
                await self.connect()

    def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        logger.info("stopping_email_monitor")
