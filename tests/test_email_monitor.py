"""Unit tests for EmailMonitor external service interactions.

Tests focus on input/output contracts for methods that interact with IMAP server.
Uses mocks to isolate external dependencies and verify behavior.
"""

import pytest
from unittest.mock import AsyncMock, Mock, MagicMock, patch
import aioimaplib

from src.email_monitor import EmailMonitor
from src.config import Settings


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    settings = Mock(spec=Settings)
    settings.imap_server = "imap.example.com"
    settings.imap_port = 993
    settings.imap_user = "test@example.com"
    settings.get_imap_password = Mock(return_value="test_password")
    settings.mailbox_name = "INBOX"
    settings.move_emails_to_mailbox = True
    settings.move_to_mailbox_name = "Processed"
    settings.sender_emails = ["info@netflix.com"]
    settings.netflix_link_patterns = ["netflix.com/account/update-primary-location"]
    settings.idle_timeout_seconds = 300
    return settings


@pytest.fixture
def email_monitor(mock_settings):
    """Create EmailMonitor instance for testing."""
    return EmailMonitor(mock_settings)


class TestEmailMonitorConnection:
    """Test IMAP connection methods with clear contracts."""

    @pytest.mark.asyncio
    async def test_connect_idle_client_success(self, email_monitor, mock_settings):
        """
        CONTRACT: _connect_idle_client()
        INPUT: Valid IMAP credentials
        OUTPUT: Idle client connected and mailbox selected
        SIDE EFFECTS: Sets self.idle_client to connected IMAP4_SSL instance
        """
        # Arrange
        mock_idle_client = AsyncMock(spec=aioimaplib.IMAP4_SSL)
        mock_idle_client.wait_hello_from_server = AsyncMock()

        # Mock successful login response
        login_response = Mock()
        login_response.result = "OK"
        mock_idle_client.login = AsyncMock(return_value=login_response)

        # Mock successful select response
        select_response = Mock()
        select_response.result = "OK"
        mock_idle_client.select = AsyncMock(return_value=select_response)

        # Patch IMAP4_SSL constructor
        with patch('aioimaplib.IMAP4_SSL', return_value=mock_idle_client):
            # Act
            await email_monitor._connect_idle_client()

        # Assert
        assert email_monitor.idle_client is mock_idle_client
        mock_idle_client.wait_hello_from_server.assert_awaited_once()
        mock_idle_client.login.assert_awaited_once_with(
            mock_settings.imap_user,
            "test_password"
        )
        mock_idle_client.select.assert_awaited_once_with("INBOX")

    @pytest.mark.asyncio
    async def test_connect_idle_client_login_failure(self, email_monitor, mock_settings):
        """
        CONTRACT: _connect_idle_client()
        INPUT: Invalid IMAP credentials
        OUTPUT: Raises aioimaplib.AioImapException
        SIDE EFFECTS: None (connection not established)
        """
        # Arrange
        mock_idle_client = AsyncMock(spec=aioimaplib.IMAP4_SSL)
        mock_idle_client.wait_hello_from_server = AsyncMock()

        # Mock failed login response
        login_response = Mock()
        login_response.result = "NO"
        mock_idle_client.login = AsyncMock(return_value=login_response)

        with patch('aioimaplib.IMAP4_SSL', return_value=mock_idle_client):
            # Act & Assert
            with pytest.raises(aioimaplib.AioImapException, match="Idle client login failed"):
                await email_monitor._connect_idle_client()

    @pytest.mark.asyncio
    async def test_connect_command_client_success(self, email_monitor, mock_settings):
        """
        CONTRACT: _connect_command_client()
        INPUT: Valid IMAP credentials
        OUTPUT: Command client connected, mailbox selected, and processed folder created
        SIDE EFFECTS: Sets self.command_client to connected IMAP4_SSL instance
        """
        # Arrange
        mock_command_client = AsyncMock(spec=aioimaplib.IMAP4_SSL)
        mock_command_client.wait_hello_from_server = AsyncMock()

        login_response = Mock()
        login_response.result = "OK"
        mock_command_client.login = AsyncMock(return_value=login_response)

        select_response = Mock()
        select_response.result = "OK"
        mock_command_client.select = AsyncMock(return_value=select_response)

        mock_command_client.create = AsyncMock()

        with patch('aioimaplib.IMAP4_SSL', return_value=mock_command_client):
            # Act
            await email_monitor._connect_command_client()

        # Assert
        assert email_monitor.command_client is mock_command_client
        mock_command_client.create.assert_awaited_once_with("Processed")

    @pytest.mark.asyncio
    async def test_disconnect_both_clients(self, email_monitor):
        """
        CONTRACT: disconnect()
        INPUT: Connected idle_client and command_client
        OUTPUT: Both clients logged out and set to None
        SIDE EFFECTS: Closes IMAP connections
        """
        # Arrange
        mock_idle = AsyncMock()
        mock_idle.logout = AsyncMock()
        email_monitor.idle_client = mock_idle

        mock_command = AsyncMock()
        mock_command.logout = AsyncMock()
        email_monitor.command_client = mock_command

        # Act
        await email_monitor.disconnect()

        # Assert
        mock_idle.logout.assert_awaited_once()
        mock_command.logout.assert_awaited_once()
        assert email_monitor.idle_client is None
        assert email_monitor.command_client is None


class TestEmailMonitorFetch:
    """Test email fetching methods with clear contracts."""

    @pytest.mark.asyncio
    async def test_fetch_email_by_id_success(self, email_monitor):
        """
        CONTRACT: fetch_email_by_id(email_uid: str)
        INPUT: Valid email UID as string (e.g., "28399")
        OUTPUT: Tuple of (email_uid, raw_email_bytes)
        SIDE EFFECTS: Executes IMAP UID FETCH command
        """
        # Arrange
        email_uid = "28399"
        mock_command_client = AsyncMock()
        email_monitor.command_client = mock_command_client

        # Mock UID FETCH response
        raw_email_data = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody'
        fetch_response = Mock()
        fetch_response.result = "OK"
        fetch_response.lines = [
            b'152 FETCH (UID 28399 BODY[] {45}',
            bytearray(raw_email_data)
        ]

        mock_command_client.uid = AsyncMock(return_value=fetch_response)

        # Act
        result = await email_monitor.fetch_email_by_id(email_uid)

        # Assert
        assert result is not None
        result_uid, result_email = result
        assert result_uid == email_uid
        assert result_email == raw_email_data
        assert isinstance(result_email, bytes)

        # Verify it used UID FETCH
        mock_command_client.uid.assert_awaited_once_with("fetch", email_uid, "(BODY.PEEK[])")

    @pytest.mark.asyncio
    async def test_fetch_email_by_id_not_found(self, email_monitor):
        """
        CONTRACT: fetch_email_by_id(email_id: str)
        INPUT: Non-existent email ID
        OUTPUT: None
        SIDE EFFECTS: Executes IMAP FETCH FLAGS command
        """
        # Arrange
        email_id = "99999"
        mock_command_client = AsyncMock()
        email_monitor.command_client = mock_command_client

        # Mock FLAGS check (email doesn't exist)
        flags_response = Mock()
        flags_response.result = "NO"
        flags_response.lines = []
        mock_command_client.fetch = AsyncMock(return_value=flags_response)

        # Act
        result = await email_monitor.fetch_email_by_id(email_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_email_by_id_unexpected_response_format(self, email_monitor):
        """
        CONTRACT: fetch_email_by_id(email_id: str)
        INPUT: Valid email ID but FETCH returns unexpected format
        OUTPUT: None
        SIDE EFFECTS: Logs warning about unexpected_fetch_response
        """
        # Arrange
        email_id = "12345"
        mock_command_client = AsyncMock()
        email_monitor.command_client = mock_command_client

        # Mock FLAGS check (email exists)
        flags_response = Mock()
        flags_response.result = "OK"
        flags_response.lines = [b'12345 FETCH (FLAGS (\\Seen))']

        # Mock FETCH with only 1 line (unexpected)
        fetch_response = Mock()
        fetch_response.result = "OK"
        fetch_response.lines = [b'Success']  # Only 1 line instead of 2+

        mock_command_client.fetch.side_effect = [flags_response, fetch_response]

        # Act
        result = await email_monitor.fetch_email_by_id(email_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_email_by_id_no_command_client(self, email_monitor):
        """
        CONTRACT: fetch_email_by_id(email_id: str)
        INPUT: Valid email ID but command_client not connected
        OUTPUT: Raises RuntimeError
        SIDE EFFECTS: None
        """
        # Arrange
        email_monitor.command_client = None

        # Act & Assert
        with pytest.raises(RuntimeError, match="IMAP command client not connected"):
            await email_monitor.fetch_email_by_id("12345")


class TestEmailMonitorMove:
    """Test email moving/marking methods with clear contracts."""

    @pytest.mark.asyncio
    async def test_move_email_to_folder_success(self, email_monitor, mock_settings):
        """
        CONTRACT: move_email_to_folder(email_uid: str)
        INPUT: Valid email UID
        OUTPUT: None
        SIDE EFFECTS:
            - Marks email as \\Seen using UID STORE
            - Copies email to move_to_mailbox_name using UID COPY
            - Marks email as \\Deleted using UID STORE
        """
        # Arrange
        email_uid = "28399"
        mock_command_client = AsyncMock()
        mock_command_client.uid = AsyncMock()
        email_monitor.command_client = mock_command_client

        # Act
        await email_monitor.move_email_to_folder(email_uid)

        # Assert - verify all UID commands were called
        # Email marked as read
        mock_command_client.uid.assert_any_call("store", email_uid, "+FLAGS", r"(\Seen)")

        # Email copied to processed folder
        mock_command_client.uid.assert_any_call("copy", email_uid, "Processed")

        # Email marked as deleted
        mock_command_client.uid.assert_any_call("store", email_uid, "+FLAGS", r"(\Deleted)")

    @pytest.mark.asyncio
    async def test_move_email_to_folder_move_disabled(self, email_monitor, mock_settings):
        """
        CONTRACT: move_email_to_folder(email_uid: str)
        INPUT: Valid email UID, move_emails_to_mailbox=False
        OUTPUT: None
        SIDE EFFECTS: Only marks email as \\Seen (no copy/delete)
        """
        # Arrange
        mock_settings.move_emails_to_mailbox = False
        email_monitor.settings = mock_settings

        email_uid = "28399"
        mock_command_client = AsyncMock()
        mock_command_client.uid = AsyncMock()
        email_monitor.command_client = mock_command_client

        # Act
        await email_monitor.move_email_to_folder(email_uid)

        # Assert
        # Verify email marked as read using UID STORE
        mock_command_client.uid.assert_awaited_once_with("store", email_uid, "+FLAGS", r"(\Seen)")

        # Verify NO copy or delete operations (only 1 uid call)
        assert mock_command_client.uid.call_count == 1

    @pytest.mark.asyncio
    async def test_expunge_deleted_success(self, email_monitor, mock_settings):
        """
        CONTRACT: expunge_deleted()
        INPUT: None
        OUTPUT: None
        SIDE EFFECTS: Executes IMAP EXPUNGE command to permanently remove deleted emails
        """
        # Arrange
        mock_command_client = AsyncMock()
        mock_command_client.expunge = AsyncMock()
        email_monitor.command_client = mock_command_client

        # Act
        await email_monitor.expunge_deleted()

        # Assert
        mock_command_client.expunge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_expunge_deleted_move_disabled(self, email_monitor, mock_settings):
        """
        CONTRACT: expunge_deleted()
        INPUT: move_emails_to_mailbox=False
        OUTPUT: None
        SIDE EFFECTS: None (expunge not called)
        """
        # Arrange
        mock_settings.move_emails_to_mailbox = False
        email_monitor.settings = mock_settings

        mock_command_client = AsyncMock()
        mock_command_client.expunge = AsyncMock()
        email_monitor.command_client = mock_command_client

        # Act
        await email_monitor.expunge_deleted()

        # Assert
        mock_command_client.expunge.assert_not_called()


class TestEmailMonitorIdle:
    """Test IMAP IDLE methods with clear contracts."""

    @pytest.mark.asyncio
    async def test_wait_for_new_emails_idle_success(self, email_monitor):
        """
        CONTRACT: wait_for_new_emails_idle(timeout: int)
        INPUT: Timeout in seconds
        OUTPUT: List of email UIDs when new emails arrive
        SIDE EFFECTS: Enters IMAP IDLE mode, uses UID SEARCH UNSEEN
        """
        # Arrange
        mock_idle_client = AsyncMock()
        mock_idle_client.idle_start = AsyncMock()
        mock_idle_client.wait_server_push = AsyncMock()
        mock_idle_client.idle_done = Mock()

        # Mock server push response with EXISTS notification
        mock_response = Mock()
        mock_response.lines = [b'28396 EXISTS']
        mock_idle_client.wait_server_push.return_value = mock_response

        # Mock command client for UID SEARCH
        mock_command_client = AsyncMock()
        search_response = Mock()
        search_response.result = "OK"
        search_response.lines = [b'SEARCH 28399 28400']
        mock_command_client.uid_search = AsyncMock(return_value=search_response)

        email_monitor.idle_client = mock_idle_client
        email_monitor.command_client = mock_command_client

        # Act
        result = await email_monitor.wait_for_new_emails_idle(timeout=1740)

        # Assert
        assert result == ["28399", "28400"]
        mock_idle_client.idle_start.assert_awaited_once_with(timeout=1740)
        mock_idle_client.wait_server_push.assert_awaited_once_with(timeout=1740)
        mock_idle_client.idle_done.assert_called_once()
        # Verify server-side filtering with FROM criteria
        mock_command_client.uid_search.assert_awaited_once_with('UNSEEN FROM "info@netflix.com"')

    @pytest.mark.asyncio
    async def test_wait_for_new_emails_idle_timeout(self, email_monitor):
        """
        CONTRACT: wait_for_new_emails_idle(timeout: int)
        INPUT: Timeout expires with no new emails
        OUTPUT: None
        SIDE EFFECTS: Enters and exits IDLE mode
        """
        # Arrange
        mock_idle_client = AsyncMock()
        mock_idle_client.idle_start = AsyncMock()
        mock_idle_client.wait_server_push = AsyncMock()
        mock_idle_client.idle_done = Mock()

        # Mock server push response with no EXISTS notification
        mock_response = Mock()
        mock_response.lines = []
        mock_idle_client.wait_server_push.return_value = mock_response

        mock_command_client = AsyncMock()

        email_monitor.idle_client = mock_idle_client
        email_monitor.command_client = mock_command_client

        # Act
        result = await email_monitor.wait_for_new_emails_idle(timeout=1740)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_new_emails_idle_not_supported(self, email_monitor):
        """
        CONTRACT: wait_for_new_emails_idle(timeout: int)
        INPUT: IMAP server doesn't support IDLE
        OUTPUT: None
        SIDE EFFECTS: Logs warning about IDLE not supported
        """
        # Arrange
        mock_idle_client = Mock()  # No idle_start method
        mock_command_client = AsyncMock()

        email_monitor.idle_client = mock_idle_client
        email_monitor.command_client = mock_command_client

        # Act
        result = await email_monitor.wait_for_new_emails_idle()

        # Assert
        assert result is None


class TestEmailMonitorSearchQuery:
    """Test IMAP search query building for server-side filtering."""

    def test_build_sender_search_query_single_sender(self, email_monitor, mock_settings):
        """
        CONTRACT: _build_sender_search_query()
        INPUT: Settings with single sender email
        OUTPUT: IMAP search query with FROM criteria
        """
        # Arrange
        mock_settings.sender_emails = ["info@netflix.com"]

        # Act
        query = email_monitor._build_sender_search_query()

        # Assert
        assert query == 'UNSEEN FROM "info@netflix.com"'

    def test_build_sender_search_query_two_senders(self, email_monitor, mock_settings):
        """
        CONTRACT: _build_sender_search_query()
        INPUT: Settings with two sender emails
        OUTPUT: IMAP search query with OR syntax for two senders
        """
        # Arrange
        mock_settings.sender_emails = ["info@netflix.com", "noreply@netflix.com"]

        # Act
        query = email_monitor._build_sender_search_query()

        # Assert
        assert query == 'UNSEEN OR FROM "info@netflix.com" FROM "noreply@netflix.com"'

    def test_build_sender_search_query_three_senders(self, email_monitor, mock_settings):
        """
        CONTRACT: _build_sender_search_query()
        INPUT: Settings with three sender emails
        OUTPUT: IMAP search query with nested OR syntax
        """
        # Arrange
        mock_settings.sender_emails = ["info@netflix.com", "noreply@netflix.com", "support@netflix.com"]

        # Act
        query = email_monitor._build_sender_search_query()

        # Assert
        assert query == 'UNSEEN OR (OR FROM "info@netflix.com" FROM "noreply@netflix.com") FROM "support@netflix.com"'

    def test_build_sender_search_query_four_senders(self, email_monitor, mock_settings):
        """
        CONTRACT: _build_sender_search_query()
        INPUT: Settings with four sender emails
        OUTPUT: IMAP search query with deeply nested OR syntax
        """
        # Arrange
        mock_settings.sender_emails = ["a@netflix.com", "b@netflix.com", "c@netflix.com", "d@netflix.com"]

        # Act
        query = email_monitor._build_sender_search_query()

        # Assert
        assert query == 'UNSEEN OR (OR (OR FROM "a@netflix.com" FROM "b@netflix.com") FROM "c@netflix.com") FROM "d@netflix.com"'


class TestEmailMonitorProcessing:
    """Test email processing orchestration with clear contracts."""

    @pytest.mark.asyncio
    async def test_process_email_by_id_success(self, email_monitor):
        """
        CONTRACT: process_email_by_id(email_id: str)
        INPUT: Valid email ID containing Netflix verification link
        OUTPUT: Verification URL as string
        SIDE EFFECTS:
            - Fetches email from IMAP
            - Processes email content
            - Marks email as read
            - Moves email to processed folder
        """
        # Arrange
        email_id = "12345"
        expected_link = "https://netflix.com/account/update-primary-location?token=abc123"

        # Mock fetch_email_by_id
        raw_email = b'''From: info@netflix.com
Subject: Important: How to update your Netflix Household
Content-Type: text/html

<html>
<body>
<a href="https://netflix.com/account/update-primary-location?token=abc123">Update Location</a>
</body>
</html>
'''
        email_monitor.fetch_email_by_id = AsyncMock(return_value=(email_id, raw_email))

        # Mock move and expunge
        email_monitor.move_email_to_folder = AsyncMock()
        email_monitor.expunge_deleted = AsyncMock()

        # Act
        result = await email_monitor.process_email_by_id(email_id)

        # Assert
        assert result == expected_link
        email_monitor.move_email_to_folder.assert_awaited_once_with(email_id)
        email_monitor.expunge_deleted.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_email_by_id_email_not_found(self, email_monitor):
        """
        CONTRACT: process_email_by_id(email_id: str)
        INPUT: Non-existent email ID
        OUTPUT: None
        SIDE EFFECTS: Attempts fetch, returns early (no move/expunge)
        """
        # Arrange
        email_id = "99999"
        email_monitor.fetch_email_by_id = AsyncMock(return_value=None)
        email_monitor.move_email_to_folder = AsyncMock()

        # Act
        result = await email_monitor.process_email_by_id(email_id)

        # Assert
        assert result is None
        email_monitor.move_email_to_folder.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_email_by_id_no_link_in_email(self, email_monitor):
        """
        CONTRACT: process_email_by_id(email_id: str)
        INPUT: Valid email ID but no Netflix link in email
        OUTPUT: None
        SIDE EFFECTS: Fetches email, processes, but doesn't move (no link found)
        """
        # Arrange
        email_id = "12345"
        raw_email = b'''From: info@netflix.com
Subject: Test
Content-Type: text/html

<html><body>No link here</body></html>
'''
        email_monitor.fetch_email_by_id = AsyncMock(return_value=(email_id, raw_email))
        email_monitor.move_email_to_folder = AsyncMock()

        # Act
        result = await email_monitor.process_email_by_id(email_id)

        # Assert
        assert result is None
        email_monitor.move_email_to_folder.assert_not_called()
