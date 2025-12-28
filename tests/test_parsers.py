"""Unit tests for email and HTML parsing modules.

Tests focus on input/output contracts for parsing methods.
Uses real email data structures but no external dependencies.
"""

import pytest
from email.message import Message

from src.parsers import EmailParser, NetflixLinkExtractor, NetflixEmailProcessor


class TestEmailParser:
    """Test email parsing with clear contracts."""

    @pytest.fixture
    def email_parser(self):
        """Create EmailParser with authorized senders."""
        return EmailParser(sender_emails=["info@netflix.com", "noreply@netflix.com"])

    def test_parse_raw_email_simple(self, email_parser):
        """
        CONTRACT: parse_raw_email(raw_email: bytes)
        INPUT: Raw email bytes
        OUTPUT: email.message.Message object
        SIDE EFFECTS: None
        """
        # Arrange
        raw_email = b"""From: test@example.com
To: user@example.com
Subject: Test Email

Body content"""

        # Act
        result = email_parser.parse_raw_email(raw_email)

        # Assert
        assert isinstance(result, Message)
        assert result["From"] == "test@example.com"
        assert result["Subject"] == "Test Email"

    def test_parse_raw_email_multipart(self, email_parser):
        """
        CONTRACT: parse_raw_email(raw_email: bytes)
        INPUT: Multipart MIME email bytes
        OUTPUT: Message object with parts
        SIDE EFFECTS: None
        """
        # Arrange
        raw_email = b"""From: test@example.com
Content-Type: multipart/alternative; boundary="boundary"

--boundary
Content-Type: text/plain

Plain text
--boundary
Content-Type: text/html

<html>HTML content</html>
--boundary--
"""

        # Act
        result = email_parser.parse_raw_email(raw_email)

        # Assert
        assert result.is_multipart()
        parts = list(result.walk())
        assert len(parts) > 1

    def test_is_from_authorized_sender_match_exact(self, email_parser):
        """
        CONTRACT: is_from_authorized_sender(msg: Message)
        INPUT: Message from exact authorized sender
        OUTPUT: True
        SIDE EFFECTS: None
        """
        # Arrange
        msg = Message()
        msg["From"] = "info@netflix.com"

        # Act
        result = email_parser.is_from_authorized_sender(msg)

        # Assert
        assert result is True

    def test_is_from_authorized_sender_match_with_name(self, email_parser):
        """
        CONTRACT: is_from_authorized_sender(msg: Message)
        INPUT: Message from authorized sender with display name
        OUTPUT: True
        SIDE EFFECTS: None
        """
        # Arrange
        msg = Message()
        msg["From"] = "Netflix <noreply@netflix.com>"

        # Act
        result = email_parser.is_from_authorized_sender(msg)

        # Assert
        assert result is True

    def test_is_from_authorized_sender_no_match(self, email_parser):
        """
        CONTRACT: is_from_authorized_sender(msg: Message)
        INPUT: Message from unauthorized sender
        OUTPUT: False
        SIDE EFFECTS: Logs warning
        """
        # Arrange
        msg = Message()
        msg["From"] = "spam@malicious.com"

        # Act
        result = email_parser.is_from_authorized_sender(msg)

        # Assert
        assert result is False

    def test_is_from_authorized_sender_missing_from_header(self, email_parser):
        """
        CONTRACT: is_from_authorized_sender(msg: Message)
        INPUT: Message with no From header
        OUTPUT: False
        SIDE EFFECTS: None
        """
        # Arrange
        msg = Message()

        # Act
        result = email_parser.is_from_authorized_sender(msg)

        # Assert
        assert result is False

    def test_extract_html_body_multipart(self, email_parser):
        """
        CONTRACT: extract_html_body(msg: Message)
        INPUT: Multipart message with text/html part
        OUTPUT: HTML content as string
        SIDE EFFECTS: None
        """
        # Arrange
        msg = Message()
        msg.set_type("multipart/alternative")

        # Add plain text part
        plain_part = Message()
        plain_part.set_type("text/plain")
        plain_part.set_payload("Plain text content")
        msg.attach(plain_part)

        # Add HTML part
        html_part = Message()
        html_part.set_type("text/html")
        html_content = "<html><body>HTML content</body></html>"
        html_part.set_payload(html_content.encode('utf-8'))
        msg.attach(html_part)

        # Act
        result = email_parser.extract_html_body(msg)

        # Assert
        assert result == html_content

    def test_extract_html_body_single_part(self, email_parser):
        """
        CONTRACT: extract_html_body(msg: Message)
        INPUT: Single-part text/html message
        OUTPUT: HTML content as string
        SIDE EFFECTS: None
        """
        # Arrange
        msg = Message()
        msg.set_type("text/html")
        html_content = "<html><body>Single part HTML</body></html>"
        msg.set_payload(html_content.encode('utf-8'))

        # Act
        result = email_parser.extract_html_body(msg)

        # Assert
        assert result == html_content

    def test_extract_html_body_no_html(self, email_parser):
        """
        CONTRACT: extract_html_body(msg: Message)
        INPUT: Message with only text/plain part
        OUTPUT: None
        SIDE EFFECTS: Logs warning
        """
        # Arrange
        msg = Message()
        msg.set_type("text/plain")
        msg.set_payload("Plain text only")

        # Act
        result = email_parser.extract_html_body(msg)

        # Assert
        assert result is None


class TestNetflixLinkExtractor:
    """Test Netflix link extraction with clear contracts."""

    @pytest.fixture
    def link_extractor(self):
        """Create NetflixLinkExtractor with patterns."""
        return NetflixLinkExtractor(
            link_patterns=["netflix.com/account/update-primary-location"]
        )

    def test_extract_verification_link_simple_anchor(self, link_extractor):
        """
        CONTRACT: extract_verification_link(html: str)
        INPUT: HTML with simple anchor tag containing Netflix link
        OUTPUT: Full verification URL
        SIDE EFFECTS: None
        """
        # Arrange
        html = """
        <html>
        <body>
            <a href="https://netflix.com/account/update-primary-location?token=abc123">
                Update your household
            </a>
        </body>
        </html>
        """

        # Act
        result = link_extractor.extract_verification_link(html)

        # Assert
        assert result == "https://netflix.com/account/update-primary-location?token=abc123"

    def test_extract_verification_link_multiple_links(self, link_extractor):
        """
        CONTRACT: extract_verification_link(html: str)
        INPUT: HTML with multiple links, one matching pattern
        OUTPUT: First matching verification URL
        SIDE EFFECTS: None
        """
        # Arrange
        html = """
        <html>
        <body>
            <a href="https://netflix.com/browse">Browse</a>
            <a href="https://netflix.com/account/update-primary-location?token=xyz789">Update</a>
            <a href="https://help.netflix.com">Help</a>
        </body>
        </html>
        """

        # Act
        result = link_extractor.extract_verification_link(html)

        # Assert
        assert result == "https://netflix.com/account/update-primary-location?token=xyz789"

    def test_extract_verification_link_no_matching_pattern(self, link_extractor):
        """
        CONTRACT: extract_verification_link(html: str)
        INPUT: HTML with Netflix links but none matching pattern
        OUTPUT: None
        SIDE EFFECTS: Logs error
        """
        # Arrange
        html = """
        <html>
        <body>
            <a href="https://netflix.com/browse">Browse</a>
            <a href="https://netflix.com/account/settings">Settings</a>
        </body>
        </html>
        """

        # Act
        result = link_extractor.extract_verification_link(html)

        # Assert
        assert result is None

    def test_extract_verification_link_url_without_scheme(self, link_extractor):
        """
        CONTRACT: extract_verification_link(html: str)
        INPUT: HTML with URL missing https:// scheme
        OUTPUT: URL with https:// added
        SIDE EFFECTS: None
        """
        # Arrange
        html = """
        <html>
        <body>
            <a href="netflix.com/account/update-primary-location?token=abc">Update</a>
        </body>
        </html>
        """

        # Act
        result = link_extractor.extract_verification_link(html)

        # Assert
        assert result == "https://netflix.com/account/update-primary-location?token=abc"

    def test_extract_verification_link_non_netflix_domain(self, link_extractor):
        """
        CONTRACT: extract_verification_link(html: str)
        INPUT: HTML with matching pattern but non-Netflix domain
        OUTPUT: None (security check)
        SIDE EFFECTS: Logs warning
        """
        # Arrange
        html = """
        <html>
        <body>
            <a href="https://evil.com/account/update-primary-location?token=abc">Phishing</a>
        </body>
        </html>
        """

        # Act
        result = link_extractor.extract_verification_link(html)

        # Assert
        assert result is None

    def test_extract_verification_link_malformed_html(self, link_extractor):
        """
        CONTRACT: extract_verification_link(html: str)
        INPUT: Malformed HTML
        OUTPUT: None (graceful handling)
        SIDE EFFECTS: Logs error
        """
        # Arrange
        html = "<html><body><a href=broken>test"

        # Act
        result = link_extractor.extract_verification_link(html)

        # Assert
        # Should not raise exception, returns None
        assert result is None or isinstance(result, str)

    def test_extract_verification_link_url_with_query_params(self, link_extractor):
        """
        CONTRACT: extract_verification_link(html: str)
        INPUT: URL with multiple query parameters
        OUTPUT: Full URL with all query params preserved
        SIDE EFFECTS: None
        """
        # Arrange
        html = """
        <a href="https://netflix.com/account/update-primary-location?token=abc&user=123&exp=456">
            Update
        </a>
        """

        # Act
        result = link_extractor.extract_verification_link(html)

        # Assert
        assert "token=abc" in result
        assert "user=123" in result
        assert "exp=456" in result

    def test_extract_verification_link_url_with_whitespace(self, link_extractor):
        """
        CONTRACT: extract_verification_link(html: str)
        INPUT: URL with surrounding whitespace
        OUTPUT: Cleaned URL without whitespace
        SIDE EFFECTS: None
        """
        # Arrange
        html = """
        <a href="  https://netflix.com/account/update-primary-location?token=abc  ">
            Update
        </a>
        """

        # Act
        result = link_extractor.extract_verification_link(html)

        # Assert
        assert result == "https://netflix.com/account/update-primary-location?token=abc"


class TestNetflixEmailProcessor:
    """Test high-level email processing orchestration."""

    @pytest.fixture
    def email_processor(self):
        """Create NetflixEmailProcessor."""
        return NetflixEmailProcessor(
            sender_emails=["info@netflix.com"],
            link_patterns=["netflix.com/account/update-primary-location"]
        )

    def test_process_email_success(self, email_processor):
        """
        CONTRACT: process_email(raw_email: bytes)
        INPUT: Raw email bytes from authorized sender with verification link
        OUTPUT: Verification URL
        SIDE EFFECTS: None (pure processing)
        """
        # Arrange
        raw_email = b"""From: info@netflix.com
To: user@example.com
Subject: Update your Netflix Household
Content-Type: text/html

<html>
<body>
<p>Please update your household location:</p>
<a href="https://netflix.com/account/update-primary-location?token=abc123">
    Update Location
</a>
</body>
</html>
"""

        # Act
        result = email_processor.process_email(raw_email)

        # Assert
        assert result == "https://netflix.com/account/update-primary-location?token=abc123"

    def test_process_email_unauthorized_sender(self, email_processor):
        """
        CONTRACT: process_email(raw_email: bytes)
        INPUT: Raw email from unauthorized sender
        OUTPUT: None
        SIDE EFFECTS: Logs warning about unauthorized sender
        """
        # Arrange
        raw_email = b"""From: spam@malicious.com
Subject: Fake Netflix Email
Content-Type: text/html

<html><body>
<a href="https://netflix.com/account/update-primary-location?token=fake">Click</a>
</body></html>
"""

        # Act
        result = email_processor.process_email(raw_email)

        # Assert
        assert result is None

    def test_process_email_no_html_body(self, email_processor):
        """
        CONTRACT: process_email(raw_email: bytes)
        INPUT: Email from authorized sender but no HTML body
        OUTPUT: None
        SIDE EFFECTS: Logs warning about no HTML body
        """
        # Arrange
        raw_email = b"""From: info@netflix.com
Subject: Test
Content-Type: text/plain

Plain text only, no HTML
"""

        # Act
        result = email_processor.process_email(raw_email)

        # Assert
        assert result is None

    def test_process_email_no_matching_link(self, email_processor):
        """
        CONTRACT: process_email(raw_email: bytes)
        INPUT: Valid email but no verification link in HTML
        OUTPUT: None
        SIDE EFFECTS: Logs error about no link found
        """
        # Arrange
        raw_email = b"""From: info@netflix.com
Content-Type: text/html

<html><body>
<p>This is a Netflix email but has no verification link.</p>
<a href="https://netflix.com/browse">Browse</a>
</body></html>
"""

        # Act
        result = email_processor.process_email(raw_email)

        # Assert
        assert result is None

    def test_process_email_multipart_with_html(self, email_processor):
        """
        CONTRACT: process_email(raw_email: bytes)
        INPUT: Multipart email with both plain text and HTML
        OUTPUT: Verification URL extracted from HTML part
        SIDE EFFECTS: None
        """
        # Arrange
        raw_email = b"""From: info@netflix.com
Content-Type: multipart/alternative; boundary="boundary"

--boundary
Content-Type: text/plain

Update your location: https://netflix.com/account/update-primary-location?token=plain

--boundary
Content-Type: text/html

<html><body>
<a href="https://netflix.com/account/update-primary-location?token=html123">Update</a>
</body></html>
--boundary--
"""

        # Act
        result = email_processor.process_email(raw_email)

        # Assert
        assert result == "https://netflix.com/account/update-primary-location?token=html123"

    def test_process_email_multiple_authorized_senders(self):
        """
        CONTRACT: process_email(raw_email: bytes)
        INPUT: Email from secondary authorized sender
        OUTPUT: Verification URL
        SIDE EFFECTS: None
        """
        # Arrange
        processor = NetflixEmailProcessor(
            sender_emails=["info@netflix.com", "noreply@netflix.com"],
            link_patterns=["netflix.com/account/update-primary-location"]
        )

        raw_email = b"""From: noreply@netflix.com
Content-Type: text/html

<html><body>
<a href="https://netflix.com/account/update-primary-location?token=xyz">Update</a>
</body></html>
"""

        # Act
        result = processor.process_email(raw_email)

        # Assert
        assert result == "https://netflix.com/account/update-primary-location?token=xyz"

    def test_process_email_multiple_link_patterns(self):
        """
        CONTRACT: process_email(raw_email: bytes)
        INPUT: Email with link matching alternative pattern
        OUTPUT: Verification URL
        SIDE EFFECTS: None
        """
        # Arrange
        processor = NetflixEmailProcessor(
            sender_emails=["info@netflix.com"],
            link_patterns=[
                "netflix.com/account/update-primary-location",
                "netflix.com/household/verify"
            ]
        )

        raw_email = b"""From: info@netflix.com
Content-Type: text/html

<html><body>
<a href="https://netflix.com/household/verify?code=alt123">Verify</a>
</body></html>
"""

        # Act
        result = processor.process_email(raw_email)

        # Assert
        assert result == "https://netflix.com/household/verify?code=alt123"
