"""Protocol definitions for dependency injection and testing.

These protocols define the interfaces that components must implement,
allowing for easy mocking and testing without tight coupling.
"""

from typing import Protocol, AsyncIterator


class EmailNotificationProvider(Protocol):
    """Protocol for email notification monitoring.

    Implementations detect when new emails arrive without processing them.
    """

    async def monitor_idle_notifications(self) -> AsyncIterator[bool]:
        """Monitor for new email notifications.

        Yields:
            True when new emails are detected
        """
        ...


class EmailProcessor(Protocol):
    """Protocol for email processing.

    Implementations fetch, parse, and extract verification links from emails.
    """

    async def process_emails(self) -> list[str]:
        """Process unread emails and extract verification links.

        Returns:
            List of verification URLs found in emails
        """
        ...


class VerificationHandler(Protocol):
    """Protocol for verification link processing.

    Implementations handle the browser automation to verify links.
    """

    async def process_link(self, link: str) -> bool:
        """Process a verification link.

        Args:
            link: Verification URL to process

        Returns:
            True if verification succeeded, False otherwise
        """
        ...


class Connectable(Protocol):
    """Protocol for components that need connection/cleanup lifecycle."""

    async def connect(self) -> None:
        """Establish connection to external service."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from external service."""
        ...

    async def initialize(self) -> None:
        """Initialize the component."""
        ...

    async def cleanup(self) -> None:
        """Clean up resources."""
        ...
