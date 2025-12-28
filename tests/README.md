# Test Suite Documentation

This directory contains comprehensive unit and integration tests for the Netflix Household Updater application.

## Test Structure

### Unit Tests with Clear Contracts

All unit tests follow a consistent CONTRACT documentation pattern:

```python
"""
CONTRACT: method_name(param: type)
INPUT: Description of inputs
OUTPUT: Description of outputs
SIDE EFFECTS: What external changes occur
ERRORS: What exceptions may be raised
"""
```

### Test Files

#### `test_email_monitor.py` - IMAP Email Monitoring Tests
**Coverage: 73% of email_monitor.py**

Tests for external IMAP service interactions with mocked dependencies.

**Test Classes:**
- `TestEmailMonitorConnection` - IMAP connection lifecycle
  - Idle client connection (success/failure)
  - Command client connection
  - Dual client disconnection

- `TestEmailMonitorFetch` - Email fetching operations
  - Fetch by ID (success/not found/unexpected format)
  - FLAGS pre-check before body fetch
  - Error handling when client not connected

- `TestEmailMonitorMove` - Email management operations
  - Mark as read, copy to folder, mark as deleted
  - Expunge deleted emails
  - Behavior when move disabled

- `TestEmailMonitorIdle` - IMAP IDLE push notifications
  - Wait for new emails
  - Timeout handling
  - Unsupported IDLE detection

- `TestEmailMonitorSearchQuery` - Server-side IMAP search query building
  - Single sender search query
  - Two senders with OR syntax
  - Three+ senders with nested OR syntax
  - Query validation for multiple authorized senders

- `TestEmailMonitorProcessing` - Email processing orchestration
  - Full processing flow (fetch → parse → move)
  - Email not found handling
  - No link in email handling

**Key Contracts:**

```python
# Dual IMAP Connection Architecture
_connect_idle_client()
  INPUT: Valid IMAP credentials from settings
  OUTPUT: None
  SIDE EFFECTS: Sets self.idle_client (dedicated to IDLE monitoring)
  ERRORS: Raises AioImapException on login/select failure

_connect_command_client()
  INPUT: Valid IMAP credentials from settings
  OUTPUT: None
  SIDE EFFECTS: Sets self.command_client (handles FETCH/STORE/COPY/EXPUNGE)
  ERRORS: Raises AioImapException on connection failure

_build_sender_search_query()
  INPUT: None (uses self.settings.sender_emails)
  OUTPUT: IMAP search query string with FROM criteria
  SIDE EFFECTS: None (pure function)
  EXAMPLES:
    - Single sender: 'UNSEEN FROM "info@netflix.com"'
    - Two senders: 'UNSEEN OR FROM "a" FROM "b"'
    - Three+ senders: 'UNSEEN OR (OR FROM "a" FROM "b") FROM "c"'

fetch_email_by_id(email_uid: str)
  INPUT: Email UID as string (e.g., "28399")
  OUTPUT: Tuple of (email_uid, raw_email_bytes) or None
  SIDE EFFECTS: Executes IMAP UID FETCH (BODY.PEEK[])
  ERRORS: Returns None on fetch failure, raises if client not connected

process_email_by_id(email_id: str)
  INPUT: Email ID as string
  OUTPUT: Verification URL string or None
  SIDE EFFECTS: Fetches email, extracts link, marks read, moves to folder
  ERRORS: Returns None on processing failure
```

#### `test_parsers.py` - Email and HTML Parsing Tests
**Coverage: 90% of parsers.py**

Tests for parsing raw email data and extracting Netflix verification links.

**Test Classes:**
- `TestEmailParser` - Raw email parsing
  - Parse simple and multipart emails
  - Authorized sender verification
  - HTML body extraction

- `TestNetflixLinkExtractor` - Link extraction from HTML
  - Extract verification links from HTML anchors
  - URL validation and cleaning
  - Security checks (Netflix domain only)
  - Query parameter preservation

- `TestNetflixEmailProcessor` - High-level processing
  - End-to-end email processing
  - Sender authorization
  - Multiple patterns and senders

**Key Contracts:**

```python
parse_raw_email(raw_email: bytes)
  INPUT: Raw email bytes from IMAP FETCH
  OUTPUT: email.message.Message object
  SIDE EFFECTS: None (pure function)

is_from_authorized_sender(msg: Message)
  INPUT: Parsed email message
  OUTPUT: Boolean (True if from authorized sender)
  SIDE EFFECTS: Logs warning for unauthorized senders

extract_verification_link(html: str)
  INPUT: HTML email content
  OUTPUT: Full verification URL or None
  SIDE EFFECTS: None (pure function)
  SECURITY: Validates netflix.com domain, cleans URL

process_email(raw_email: bytes)
  INPUT: Raw email bytes
  OUTPUT: Verification URL string or None
  SIDE EFFECTS: None (pure processing)
  FLOW: parse → verify sender → extract HTML → extract link
```

#### `test_browser_simple.py` - Browser Automation Contracts
**Coverage: 20% of browser.py** (integration tests needed for full coverage)

Tests for Playwright browser automation lifecycle and contracts.

**Test Classes:**
- `TestBrowserLifecycleContracts` - Initialization and cleanup
  - Browser initialization
  - Graceful cleanup
  - Partial initialization handling

- `TestVerificationLinkContracts` - Verification processing
  - Requires initialization check
  - Input/output contract verification

- `TestBrowserContractDocumentation` - Integration test guides
  - Documents expected behavior for integration tests
  - Timing metrics documentation
  - Retry behavior documentation

**Key Contracts:**

```python
initialize()
  INPUT: None
  OUTPUT: None
  SIDE EFFECTS: Creates Playwright, Browser, Context
  ERRORS: Raises on Playwright startup failure

cleanup()
  INPUT: None
  OUTPUT: None
  SIDE EFFECTS: Closes all browser resources
  ERRORS: Logs warnings but doesn't raise (graceful shutdown)

process_verification_link(url: str)
  INPUT: Netflix verification URL
  OUTPUT: Boolean (True on success)
  SIDE EFFECTS: Creates page, navigates, clicks confirmation, closes page
  RETRIES: Up to 3 times with exponential backoff (2-10s)
  TIMING: Logs detailed breakdown of each step
```

#### `test_concurrent_performance.py` - Performance Tests
**Coverage: Integration testing**

Tests concurrent behavior of email detection and browser verification.

**Test Cases:**
- Concurrent email detection during verification
- Rapid email arrivals handling
- IDLE resume speed after email processing

#### `test_doubles.py` - Test Fakes and Mocks

Reusable test doubles for integration testing:
- `FakeEmailMonitor` - Simulated email arrivals with controlled timing
- `FakeBrowserPool` - Simulated browser verification
- `RecordingEmailMonitor` - Wraps real monitor to record timings
- `RecordingBrowserPool` - Wraps real pool to record timings

## Running Tests

### Run All Tests
```bash
pytest tests/ -v
```

### Run Specific Test File
```bash
pytest tests/test_email_monitor.py -v
```

### Run Specific Test Class
```bash
pytest tests/test_email_monitor.py::TestEmailMonitorFetch -v
```

### Run Specific Test
```bash
pytest tests/test_email_monitor.py::TestEmailMonitorFetch::test_fetch_email_by_id_success -v
```

### Run with Coverage
```bash
pytest tests/ --cov=src --cov-report=html
```

### Run Fast (Skip Slow Integration Tests)
```bash
pytest tests/ -m "not slow"
```

## Test Coverage Summary

| Module | Coverage | Notes |
|--------|----------|-------|
| parsers.py | 90% | Excellent unit test coverage |
| email_monitor.py | 73% | Good coverage of IMAP operations |
| metrics.py | 87% | Well tested |
| config.py | 65% | Core functionality tested |
| main.py | 65% | Integration paths tested |
| browser.py | 20% | Needs integration tests with real browser |

## Writing New Tests

### Follow the CONTRACT Pattern

Every test should document the contract:

```python
@pytest.mark.asyncio
async def test_my_method_success(self):
    """
    CONTRACT: my_method(param: str)
    INPUT: Valid parameter value
    OUTPUT: Expected return value
    SIDE EFFECTS: What external changes occur
    ERRORS: What exceptions may be raised
    """
    # Arrange
    # ... setup

    # Act
    result = await my_method("input")

    # Assert
    assert result == expected
```

### Use Clear Test Names

Test names should describe:
1. What is being tested
2. Under what conditions
3. What the expected outcome is

Examples:
- `test_fetch_email_by_id_success` - Happy path
- `test_fetch_email_by_id_not_found` - Error case
- `test_move_email_to_folder_move_disabled` - Edge case

### Mock External Dependencies

- Use `AsyncMock` for async methods
- Use `Mock` for sync methods
- Use `patch` to replace external services
- Verify mock calls with `assert_awaited_once()` etc.

### Test Both Success and Failure Paths

For each method, test:
1. Success case (happy path)
2. Expected failures (not found, invalid input)
3. Edge cases (empty input, None values)
4. Error conditions (disconnected, timeout)

## Integration Testing

Some components require integration tests with real external services:

### Browser Automation
Full browser testing requires:
- Playwright installed
- Browser binaries
- Real Netflix test account
- Network connectivity

Run integration tests separately:
```bash
pytest tests/ -m integration
```

### IMAP Testing
Real IMAP testing requires:
- IMAP server access
- Valid credentials
- Test mailbox

Use test doubles for unit tests, integration tests for E2E validation.

## Continuous Integration

Tests are run automatically on:
- Every commit
- Pull requests
- Pre-push hooks

CI Configuration:
- All unit tests must pass
- Code coverage must not decrease
- No new linting errors
