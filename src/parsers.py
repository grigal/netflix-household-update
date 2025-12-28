"""Email and HTML parsing utilities."""

import email
import re
from email.message import Message
from typing import Optional
from urllib.parse import urlparse

import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger(__name__)


class EmailParser:
    """Parse IMAP email messages."""

    def __init__(self, sender_emails: list[str]):
        """Initialize parser with authorized sender addresses.

        Args:
            sender_emails: List of authorized Netflix sender email addresses
        """
        self.sender_emails = sender_emails

    def parse_raw_email(self, raw_email: bytes) -> Message:
        """Parse raw email bytes into Message object.

        Args:
            raw_email: Raw email data from IMAP fetch

        Returns:
            Parsed email message
        """
        return email.message_from_bytes(raw_email)

    def is_from_authorized_sender(self, msg: Message) -> bool:
        """Check if email is from an authorized Netflix sender.

        Args:
            msg: Parsed email message

        Returns:
            True if sender is authorized
        """
        sender = msg.get("From", "")

        # Debug: log all headers
        logger.info("email_headers_debug",
                   from_header=sender,
                   subject=msg.get("Subject", ""),
                   all_keys=list(msg.keys())[:10])  # First 10 headers

        is_authorized = any(authorized in sender for authorized in self.sender_emails)

        if is_authorized:
            logger.info("email_from_authorized_sender", sender=sender)
        else:
            logger.warning("email_from_unauthorized_sender", sender=sender)

        return is_authorized

    def is_household_update_email(self, msg: Message) -> bool:
        """Check if email is a Netflix household update email by subject.

        Args:
            msg: Parsed email message

        Returns:
            True if subject contains household update text
        """
        subject = msg.get("Subject", "")

        is_household_update = "Important: How to update your Netflix Household" in subject

        if is_household_update:
            logger.info("email_is_household_update", subject=subject)
        else:
            logger.info("email_filtered_by_subject",
                       subject=subject,
                       reason="Not a household update email")

        return is_household_update

    def extract_html_body(self, msg: Message) -> Optional[str]:
        """Extract HTML body from multipart email.

        Args:
            msg: Parsed email message

        Returns:
            HTML content or None if not found
        """
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
        else:
            # Single part message
            if msg.get_content_type() == "text/html":
                payload = msg.get_payload(decode=True)
                if payload:
                    return payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")

        logger.warning("no_html_body_found")
        return None


class NetflixLinkExtractor:
    """Extract Netflix household verification links from HTML."""

    def __init__(self, link_patterns: list[str]):
        """Initialize extractor with URL patterns to match.

        Args:
            link_patterns: List of URL patterns to search for
        """
        self.link_patterns = link_patterns

    def extract_verification_link(self, html: str) -> Optional[str]:
        """Extract Netflix verification link from HTML email body.

        Uses BeautifulSoup for robust HTML parsing instead of regex.

        Args:
            html: HTML email content

        Returns:
            Full verification URL or None if not found
        """
        try:
            soup = BeautifulSoup(html, "lxml")

            # Find all links in the email
            for link in soup.find_all("a", href=True):
                href = link["href"]

                # Check if this matches any of our patterns
                for pattern in self.link_patterns:
                    if pattern in href:
                        verified_url = self._validate_and_clean_url(href)
                        if verified_url:
                            logger.info("netflix_link_extracted", url=verified_url)
                            return verified_url

            logger.error("no_netflix_link_found_in_html")
            return None

        except Exception as e:
            logger.error("html_parsing_failed", error=str(e), exc_info=True)
            return None

    def _validate_and_clean_url(self, url: str) -> Optional[str]:
        """Validate and clean extracted URL.

        Args:
            url: Raw URL from email

        Returns:
            Cleaned, validated URL or None if invalid
        """
        try:
            # Remove any whitespace
            url = url.strip()

            # Ensure URL has scheme
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"

            # Parse to validate
            parsed = urlparse(url)

            # Verify it's a Netflix domain
            if "netflix.com" not in parsed.netloc:
                logger.warning("url_not_netflix_domain", url=url)
                return None

            # Reconstruct clean URL
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"

            return clean_url

        except Exception as e:
            logger.error("url_validation_failed", url=url, error=str(e))
            return None


class NetflixEmailProcessor:
    """High-level email processing orchestrator."""

    def __init__(
        self,
        sender_emails: list[str],
        link_patterns: list[str],
    ):
        """Initialize email processor.

        Args:
            sender_emails: Authorized sender addresses
            link_patterns: URL patterns to match
        """
        self.email_parser = EmailParser(sender_emails)
        self.link_extractor = NetflixLinkExtractor(link_patterns)

    def process_email(self, raw_email: bytes) -> Optional[str]:
        """Process raw email and extract verification link.

        Args:
            raw_email: Raw email bytes from IMAP

        Returns:
            Verification URL or None if processing failed
        """
        # Parse email
        msg = self.email_parser.parse_raw_email(raw_email)

        # Verify sender
        if not self.email_parser.is_from_authorized_sender(msg):
            return None

        # Check if this is a household update email by subject
        if not self.email_parser.is_household_update_email(msg):
            return None

        # Extract HTML body
        html = self.email_parser.extract_html_body(msg)
        if not html:
            return None

        # Extract verification link
        return self.link_extractor.extract_verification_link(html)
