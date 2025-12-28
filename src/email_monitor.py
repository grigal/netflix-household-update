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

    async def move_email_to_folder(self, email_uid: str) -> None:
        """Mark email as read, move to processed folder, and mark as deleted.

        Args:
            email_uid: Email UID to move
        """
        if not self.command_client:
            raise RuntimeError("IMAP command client not connected")

        try:
            # Use UID STORE to mark as read (permanent identifier)
            await self.command_client.uid("store", email_uid, "+FLAGS", r"(\Seen)")

            if self.settings.move_emails_to_mailbox:
                # Use UID COPY to copy to processed folder
                await self.command_client.uid("copy", email_uid, self.settings.move_to_mailbox_name)
                # Use UID STORE to mark as deleted
                await self.command_client.uid("store", email_uid, "+FLAGS", r"(\Deleted)")

            logger.debug("email_processed_and_moved", uid=email_uid)

        except Exception as e:
            logger.error(
                "email_move_failed",
                uid=email_uid,
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

    def _build_sender_search_query(self) -> str:
        """Build IMAP search query with FROM criteria for authorized senders.

        Returns:
            IMAP search query string (e.g., 'UNSEEN FROM "sender@example.com"')
        """
        senders = self.settings.sender_emails

        # Single sender case
        if len(senders) == 1:
            return f'UNSEEN FROM "{senders[0]}"'

        # Multiple senders - use IMAP OR syntax
        # Two senders: UNSEEN OR FROM "a" FROM "b"
        if len(senders) == 2:
            return f'UNSEEN OR FROM "{senders[0]}" FROM "{senders[1]}"'

        # Three or more senders: UNSEEN OR (OR FROM "a" FROM "b") FROM "c"
        # Build nested OR structure
        query = f'OR FROM "{senders[0]}" FROM "{senders[1]}"'
        for sender in senders[2:]:
            query = f'OR ({query}) FROM "{sender}"'

        return f'UNSEEN {query}'

    async def wait_for_new_emails_idle(self, timeout: Optional[int] = None) -> Optional[list[str]]:
        """Wait for new emails using IMAP IDLE (push notifications).

        Uses server-side filtering (UID SEARCH UNSEEN FROM) to only return emails
        from authorized senders, dramatically reducing overhead when many unseen
        emails exist from other senders.

        Args:
            timeout: IDLE timeout in seconds (uses settings.idle_timeout_seconds if None)

        Returns:
            List of email UIDs from authorized senders if new emails arrived, None if timeout or error
        """
        if timeout is None:
            timeout = self.settings.idle_timeout_seconds
        if not self.idle_client:
            raise RuntimeError("IMAP idle client not connected")

        if not self.command_client:
            raise RuntimeError("IMAP command client not connected")

        try:
            if not hasattr(self.idle_client, "idle_start"):
                logger.warning("imap_idle_not_supported")
                return None

            logger.debug("entering_idle_mode", timeout=timeout)

            await self.idle_client.idle_start(timeout=timeout)
            result = await self.idle_client.wait_server_push(timeout=timeout)
            self.idle_client.idle_done()

            # Handle both Response namedtuple and raw list (aioimaplib inconsistency)
            lines = result.lines if hasattr(result, 'lines') else result

            # Early return if no server push lines
            if not lines:
                logger.info("idle_timeout_no_new_emails")
                return None

            # During IDLE, server can send: EXISTS (new mail), EXPUNGE (deleted), FETCH (flags changed)
            # We only care about EXISTS - new mail arrived
            for line in lines:
                if b"EXISTS" in line:
                    logger.info("idle_received_exists", line=str(line))
                    return await self._fetch_uids_from_exists(line)

            # No EXISTS notification - EXPUNGE or FETCH only
            logger.debug("idle_notification_not_exists",
                        lines=[str(line) for line in lines])
            return None

        except asyncio.TimeoutError:
            logger.debug("idle_timeout_expired")
            return None
        except Exception as e:
            logger.warning("idle_mode_failed",
                          error=str(e),
                          error_type=type(e).__name__,
                          exc_info=True)
            return None

    async def _fetch_uids_from_exists(self, exists_line: bytes) -> Optional[list[str]]:
        """Fetch UIDs after receiving EXISTS notification.

        Args:
            exists_line: IMAP EXISTS response line (e.g., b'28396 EXISTS')

        Returns:
            List of email UIDs from authorized senders, or None if none found
        """
        try:
            exists_count = exists_line.split()[0].decode()
            logger.debug("exists_notification", exists_count=exists_count)

            # Time the UID resolution overhead
            import time
            uid_start = time.time()

            # Build server-side IMAP search with FROM filter
            # This dramatically reduces overhead when many unseen emails exist
            search_query = self._build_sender_search_query()
            logger.debug("executing_uid_search", query=search_query)
            search_result = await self.command_client.uid_search(search_query)
            logger.debug("uid_search_result", result=search_result.result,
                        lines=[line.decode() if isinstance(line, bytes) else str(line) for line in search_result.lines] if search_result.lines else [])

            uid_overhead = time.time() - uid_start

            # Early return if search failed
            if search_result.result != "OK" or len(search_result.lines) < 1:
                logger.debug("no_unseen_emails_found")
                return None

            # Parse UIDs from search result
            # Gmail returns: ['65490', 'SEARCH completed (Success)']
            # Other servers may return: [b'SEARCH 65490 65491']
            search_line = search_result.lines[0]

            # Handle both bytes and string responses
            if isinstance(search_line, bytes):
                search_line_str = search_line.decode()
            else:
                search_line_str = str(search_line)

            # Extract UIDs - handle both formats
            if search_line_str.startswith('SEARCH'):
                # Format: "SEARCH 65490 65491"
                parts = search_line_str.split()
                uids = [uid for uid in parts[1:] if uid.isdigit()]
            else:
                # Format: "65490" or "65490 65491" (Gmail style - UIDs without SEARCH keyword)
                parts = search_line_str.split()
                uids = [uid for uid in parts if uid.isdigit()]

            if not uids:
                logger.debug("no_unseen_emails_found")
                return None

            logger.info("new_emails_detected",
                       uid_count=len(uids),
                       uid_resolution_ms=round(uid_overhead * 1000, 1))
            return uids

        except (ValueError, IndexError) as e:
            logger.warning("failed_to_resolve_uids", error=str(e))
            return None

    async def fetch_email_by_id(self, email_uid: str) -> Optional[tuple[str, bytes]]:
        """Fetch a specific email by UID.

        Args:
            email_uid: IMAP email UID (permanent identifier)

        Returns:
            Tuple of (email_uid, raw_email_data) or None if not found
        """
        if not self.command_client:
            raise RuntimeError("IMAP command client not connected")

        try:
            logger.debug("fetching_email_by_uid", uid=email_uid)

            # Use UID FETCH to fetch by permanent UID instead of sequence number
            # This is race-condition free and works even if messages are deleted
            result = await self.command_client.uid("fetch", email_uid, "(BODY.PEEK[])")

            if result.result != "OK":
                logger.warning("uid_fetch_failed", uid=email_uid, result=str(result))
                return None

            # aioimaplib UID FETCH response structure:
            # result.lines[0]: b'SEQ FETCH (UID 28399 BODY[] {size}' or similar
            # result.lines[1]: bytearray or bytes with actual email data

            if len(result.lines) >= 2:
                raw_email = result.lines[1]

                # Convert bytearray to bytes if needed
                if isinstance(raw_email, bytearray):
                    raw_email = bytes(raw_email)

                return (email_uid, raw_email)

            logger.warning("unexpected_uid_fetch_response", uid=email_uid)
            return None

        except Exception as e:
            logger.error("fetch_email_by_uid_failed", uid=email_uid, error=str(e), exc_info=True)
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
        just detects that they arrived and yields email UIDs.

        Yields:
            Email UID when new emails are detected
        """
        self._running = True
        logger.info("starting_idle_notification_monitoring")

        while self._running:
            try:
                # Wait for new emails (IDLE active here - fast detection)
                email_uids = await self.wait_for_new_emails_idle()

                if email_uids:
                    # Yield each UID for processing
                    for uid in email_uids:
                        yield uid

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
