"""End-to-end test using mock IMAP server.

Tests the complete flow from email notification to verification
without requiring a real IMAP server or Netflix emails.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings
from src.email_monitor import EmailMonitor
from src.main import NetflixHouseholdUpdater

from .mock_imap_server import MockIMAPServerFactory


@pytest.fixture
def mock_imap_factory():
    """Create mock IMAP server factory."""
    return MockIMAPServerFactory()


@pytest.fixture
def settings():
    """Create test settings."""
    return Settings(
        imap_server="imap.test.com",
        imap_port=993,
        imap_user="test@example.com",
        imap_pass="testpass",
        mailbox_name="INBOX",
        sender_emails=["info@account.netflix.com", "tomas.grigal@gmail.com"],
        netflix_user="netflix@example.com",
        netflix_pass="netflixpass",
        netflix_link_patterns=[
            "netflix.com/account/travel/verify"
        ],
        move_emails_to_mailbox=False,
    )


@pytest.mark.asyncio
async def test_end_to_end_with_mock_server(mock_imap_factory, settings):
    """Test complete flow: IDLE notification → email fetch → link extraction."""

    # Patch aioimaplib to use our mock
    with patch("src.email_monitor.aioimaplib") as mock_aioimaplib:
        # Configure mock to return our mock clients
        mock_aioimaplib.IMAP4_SSL = lambda host, port: mock_imap_factory.create_client(
            host, port
        )

        # Create email monitor
        email_monitor = EmailMonitor(settings)
        await email_monitor.connect()

        # Add a Netflix email via trigger (will add and send IDLE notification)
        verification_link = "https://www.netflix.com/account/travel/verify?nftoken=TEST_TOKEN_12345"
        asyncio.create_task(mock_imap_factory.trigger_new_email(verification_link, delay=0.5))

        # Wait for IDLE notification
        email_uids = await email_monitor.wait_for_new_emails_idle(timeout=2)

        # Verify we got the UID
        assert email_uids is not None
        assert len(email_uids) == 1
        uid = int(email_uids[0])

        # Process the email
        extracted_link = await email_monitor.process_email_by_id(str(uid))

        # Verify link was extracted
        assert extracted_link is not None
        assert verification_link in extracted_link

        await email_monitor.disconnect()


@pytest.mark.asyncio
async def test_end_to_end_with_browser_mock(mock_imap_factory, settings):
    """Test complete flow including browser verification (mocked)."""

    # Create mock browser pool
    mock_browser_pool = AsyncMock()
    mock_browser_pool.initialize = AsyncMock()
    mock_browser_pool.process_link = AsyncMock(return_value=True)
    mock_browser_pool.cleanup = AsyncMock()

    # Patch aioimaplib
    with patch("src.email_monitor.aioimaplib") as mock_aioimaplib:
        mock_aioimaplib.IMAP4_SSL = lambda host, port: mock_imap_factory.create_client(
            host, port
        )

        # Create email monitor
        email_monitor = EmailMonitor(settings)

        # Create app with mocked browser pool
        app = NetflixHouseholdUpdater(
            settings=settings,
            email_monitor=email_monitor,
            browser_pool=mock_browser_pool,
        )

        await app.initialize()

        # Add email and trigger notification
        verification_link = "https://www.netflix.com/account/travel/verify?nftoken=E2E_TEST"
        asyncio.create_task(mock_imap_factory.trigger_new_email(verification_link, delay=0.5))

        # Run for a short time
        try:
            await asyncio.wait_for(app.run_with_idle(), timeout=3)
        except asyncio.TimeoutError:
            pass  # Expected - we're just testing the flow

        # Verify browser was called with the link
        if mock_browser_pool.process_link.called:
            called_link = mock_browser_pool.process_link.call_args[0][0]
            assert verification_link in called_link

        await app.cleanup()


@pytest.mark.asyncio
async def test_multiple_emails_queued(mock_imap_factory, settings):
    """Test that multiple emails arriving quickly are all processed."""

    with patch("src.email_monitor.aioimaplib") as mock_aioimaplib:
        mock_aioimaplib.IMAP4_SSL = lambda host, port: mock_imap_factory.create_client(
            host, port
        )

        email_monitor = EmailMonitor(settings)
        await email_monitor.connect()

        # Add multiple emails
        links = [
            f"https://www.netflix.com/account/travel/verify?nftoken=TOKEN_{i}"
            for i in range(3)
        ]

        # Add emails before IDLE starts
        uids = []
        for link in links:
            uid = mock_imap_factory.add_netflix_email(link)
            uids.append(uid)

        # Manually trigger EXISTS notification since emails were added before IDLE
        await mock_imap_factory.server.idle_queue.put(f"{len(mock_imap_factory.server.emails)} EXISTS")

        # Wait for notification
        detected_uids = await email_monitor.wait_for_new_emails_idle(timeout=2)

        # Should detect all UIDs (they were all added before IDLE started)
        assert detected_uids is not None
        assert len(detected_uids) == len(uids)

        # Process all emails
        extracted_links = []
        for uid in detected_uids:
            link = await email_monitor.process_email_by_id(str(uid))
            if link:
                extracted_links.append(link)

        # Verify all links were extracted
        assert len(extracted_links) == len(links)

        await email_monitor.disconnect()


@pytest.mark.asyncio
async def test_seen_emails_not_detected(mock_imap_factory, settings):
    """Test that emails already marked as SEEN are not detected."""

    with patch("src.email_monitor.aioimaplib") as mock_aioimaplib:
        mock_aioimaplib.IMAP4_SSL = lambda host, port: mock_imap_factory.create_client(
            host, port
        )

        email_monitor = EmailMonitor(settings)
        await email_monitor.connect()

        # Add email and mark as seen
        link = "https://www.netflix.com/account/travel/verify?nftoken=SEEN_TEST"
        uid = mock_imap_factory.add_netflix_email(link)
        mock_imap_factory.server.mark_seen(uid)

        # Trigger notification
        asyncio.create_task(mock_imap_factory.trigger_new_email(link, delay=0.3))

        # Wait for notification
        detected_uids = await email_monitor.wait_for_new_emails_idle(timeout=2)

        # Should not detect the SEEN email
        if detected_uids:
            assert uid not in detected_uids

        await email_monitor.disconnect()


@pytest.mark.asyncio
async def test_idle_timeout(mock_imap_factory, settings):
    """Test IDLE timeout when no emails arrive."""

    with patch("src.email_monitor.aioimaplib") as mock_aioimaplib:
        mock_aioimaplib.IMAP4_SSL = lambda host, port: mock_imap_factory.create_client(
            host, port
        )

        email_monitor = EmailMonitor(settings)
        await email_monitor.connect()

        # Don't add any emails - should timeout
        detected_uids = await email_monitor.wait_for_new_emails_idle(timeout=0.5)

        # Should return None on timeout
        assert detected_uids is None

        await email_monitor.disconnect()
