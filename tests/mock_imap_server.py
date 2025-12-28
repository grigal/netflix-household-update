"""Mock IMAP server for end-to-end testing.

Simulates a real IMAP server that sends IDLE notifications and returns
Netflix verification emails with real verification links.
"""

import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional


class MockIMAPServer:
    """Mock IMAP server for testing.

    Simulates IMAP IDLE, SEARCH, and FETCH operations with realistic
    Netflix verification emails.
    """

    def __init__(self):
        """Initialize mock server."""
        self.emails = []
        self.current_uid = 65490
        self.idle_active = False
        self.idle_queue = asyncio.Queue()

    def add_netflix_email(self, verification_link: Optional[str] = None) -> int:
        """Add a Netflix verification email to the server.

        Args:
            verification_link: Verification link to include (generates fake one if None)

        Returns:
            UID of the added email
        """
        if verification_link is None:
            verification_link = f"https://www.netflix.com/account/travel/verify?nftoken=MOCK_TOKEN_{self.current_uid}"

        # Create realistic Netflix HTML email
        msg = MIMEMultipart('alternative')
        msg['From'] = 'Netflix <info@account.netflix.com>'
        msg['To'] = 'tomas.grigal@gmail.com'
        msg['Subject'] = 'Important: How to update your Netflix Household'

        html = f"""
        <html>
        <body>
            <h1>Update your Netflix Household</h1>
            <p>We noticed you're watching Netflix from a new location.</p>
            <p>To continue watching, please verify this device:</p>
            <a href="{verification_link}">Verify Device</a>
            <p>Or copy this link: {verification_link}</p>
        </body>
        </html>
        """

        html_part = MIMEText(html, 'html')
        msg.attach(html_part)

        email_data = {
            'uid': self.current_uid,
            'flags': [],  # UNSEEN by default
            'raw': msg.as_bytes(),
        }

        self.emails.append(email_data)
        uid = self.current_uid
        self.current_uid += 1

        # Trigger IDLE notification if active
        if self.idle_active:
            asyncio.create_task(self._send_idle_notification(len(self.emails)))

        return uid

    async def _send_idle_notification(self, exists_count: int):
        """Send EXISTS notification to IDLE queue."""
        await asyncio.sleep(0.1)  # Small delay to simulate network
        await self.idle_queue.put(f"{exists_count} EXISTS")

    def get_email_by_uid(self, uid: int) -> Optional[dict]:
        """Get email by UID."""
        for email in self.emails:
            if email['uid'] == uid:
                return email
        return None

    def search_unseen_from(self, sender: str) -> list[int]:
        """Search for UNSEEN emails from sender."""
        uids = []
        for email in self.emails:
            # Check if UNSEEN (no Seen flag)
            if '\\Seen' not in email['flags']:
                # Parse From header
                raw = email['raw'].decode('utf-8', errors='ignore')
                if sender.lower() in raw.lower():
                    uids.append(email['uid'])
        return uids

    def mark_seen(self, uid: int):
        """Mark email as seen."""
        email = self.get_email_by_uid(uid)
        if email and '\\Seen' not in email['flags']:
            email['flags'].append('\\Seen')


class MockIMAP4_SSL:
    """Mock aioimaplib IMAP4_SSL client.

    Simulates the aioimaplib.IMAP4_SSL interface for testing.
    """

    def __init__(self, server: MockIMAPServer, host: str, port: int):
        """Initialize mock IMAP client.

        Args:
            server: Mock server instance
            host: IMAP host (ignored)
            port: IMAP port (ignored)
        """
        self.server = server
        self.host = host
        self.port = port
        self.state = "NOT_AUTHENTICATED"

    async def wait_hello_from_server(self):
        """Simulate server hello."""
        await asyncio.sleep(0.01)

    async def login(self, user: str, password: str):
        """Simulate login."""
        await asyncio.sleep(0.01)
        self.state = "AUTHENTICATED"

        class Response:
            result = "OK"
            lines = [b"LOGIN completed"]

        return Response()

    async def select(self, mailbox: str):
        """Simulate mailbox selection."""
        await asyncio.sleep(0.01)
        self.state = "SELECTED"

        class Response:
            result = "OK"
            lines = [f"{len(self.server.emails)} EXISTS".encode()]

        return Response()

    async def create(self, mailbox: str):
        """Simulate mailbox creation."""
        await asyncio.sleep(0.01)

        class Response:
            result = "OK"
            lines = [b"CREATE completed"]

        return Response()

    async def logout(self):
        """Simulate logout."""
        await asyncio.sleep(0.01)
        self.state = "LOGOUT"

        class Response:
            result = "OK"
            lines = [b"LOGOUT completed"]

        return Response()

    async def idle_start(self, timeout: int = 1740):
        """Simulate IDLE start."""
        self.server.idle_active = True
        await asyncio.sleep(0.01)

    def idle_done(self):
        """Simulate IDLE done."""
        self.server.idle_active = False

    async def wait_server_push(self, timeout: float = 1740):
        """Simulate waiting for server push notifications."""
        try:
            line = await asyncio.wait_for(self.server.idle_queue.get(), timeout=timeout)

            class Response:
                result = "OK"
                lines = [line.encode()]

            return Response()
        except asyncio.TimeoutError:
            class Response:
                result = "OK"
                lines = []

            return Response()

    async def uid_search(self, *criteria):
        """Simulate UID SEARCH."""
        await asyncio.sleep(0.01)

        # Parse search criteria
        search_str = ' '.join(str(c) for c in criteria)

        # Extract sender from "UNSEEN FROM sender@example.com" or similar
        sender = None
        if 'FROM' in search_str:
            parts = search_str.split('FROM')
            if len(parts) > 1:
                # Get first sender (handles OR queries too)
                sender_part = parts[1].strip().split()[0].strip('"\'')
                sender = sender_part

        # Search for matching UIDs
        if sender:
            # Check if UNSEEN is in criteria
            if 'UNSEEN' in search_str:
                uids = self.server.search_unseen_from(sender)
            else:
                # All emails from sender (seen or unseen)
                uids = []
                for email in self.server.emails:
                    raw = email['raw'].decode('utf-8', errors='ignore')
                    if sender.lower() in raw.lower():
                        uids.append(email['uid'])
        else:
            uids = []

        # Format response
        if uids:
            uid_str = ' '.join(str(uid) for uid in uids)
            response_line = f"SEARCH {uid_str}".encode()
        else:
            response_line = b""

        class Response:
            result = "OK"
            lines = [response_line]

        return Response()

    async def uid(self, command: str, *args):
        """Simulate UID commands (FETCH, STORE, COPY)."""
        await asyncio.sleep(0.01)

        if command.lower() == "fetch":
            uid = int(args[0])
            email = self.server.get_email_by_uid(uid)

            if email:
                # Return email data
                class Response:
                    result = "OK"
                    lines = [
                        f"{uid} FETCH (UID {uid} BODY[] {{size}})".encode(),
                        email['raw'],
                        b")",
                        b"Success"
                    ]

                return Response()
            else:
                class Response:
                    result = "OK"
                    lines = [b"Success"]

                return Response()

        elif command.lower() == "store":
            uid = int(args[0])
            flags = args[1]

            if "+FLAGS" in flags and "Seen" in str(args):
                self.server.mark_seen(uid)

            class Response:
                result = "OK"
                lines = [b"STORE completed"]

            return Response()

        elif command.lower() == "copy":
            class Response:
                result = "OK"
                lines = [b"COPY completed"]

            return Response()

        else:
            class Response:
                result = "OK"
                lines = []

            return Response()

    async def expunge(self):
        """Simulate EXPUNGE."""
        await asyncio.sleep(0.01)

        class Response:
            result = "OK"
            lines = [b"EXPUNGE completed"]

        return Response()


class MockIMAPServerFactory:
    """Factory for creating mock IMAP clients connected to the same server."""

    def __init__(self):
        """Initialize factory with shared server."""
        self.server = MockIMAPServer()

    def create_client(self, host: str, port: int) -> MockIMAP4_SSL:
        """Create a new mock IMAP client.

        Args:
            host: IMAP host (ignored)
            port: IMAP port (ignored)

        Returns:
            Mock IMAP client connected to shared server
        """
        return MockIMAP4_SSL(self.server, host, port)

    def add_netflix_email(self, verification_link: Optional[str] = None) -> int:
        """Add a Netflix email to the server.

        Args:
            verification_link: Verification link to include

        Returns:
            UID of added email
        """
        return self.server.add_netflix_email(verification_link)

    async def trigger_new_email(self, verification_link: Optional[str] = None, delay: float = 0.5):
        """Trigger a new email arrival after a delay.

        Useful for testing IDLE notifications.

        Args:
            verification_link: Verification link to include
            delay: Delay in seconds before email arrives

        Returns:
            UID of added email
        """
        await asyncio.sleep(delay)
        return self.add_netflix_email(verification_link)
