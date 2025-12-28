# Netflix Household Updater

Automated Netflix household location verification using async Python. Monitors your email inbox via IMAP IDLE (push notifications), extracts verification links, and uses headless browser automation to confirm household updates.

## Features

- **IMAP IDLE monitoring** - Push notifications instead of polling (instant detection)
- **Dual-queue architecture** - Parallel email detection during browser verification
- **UID-based operations** - Race-condition free email handling
- **Subject-based filtering** - Only processes household update emails
- **Configurable IDLE timeout** - Optimized for Gmail (default 5 minutes)
- **End-to-end timing metrics** - Performance tracking from notification to verification
- **Automatic email management** - Moves processed emails to separate folder
- **Structured logging** - JSON-compatible logs for monitoring
- **Comprehensive testing** - 62 tests with mock IMAP server

## Quick Start

### Installation

**Requirements:** Python 3.11+

```bash
# Clone repository
git clone https://github.com/grigal/netflix-household-update.git
cd netflix-household-update

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .

# Install Playwright browsers
playwright install chromium
```

### Configuration

Create a `.env` file with your credentials:

```bash
# Required
IMAP_SERVER=imap.gmail.com
IMAP_USER=your@email.com
IMAP_PASS=your_app_password
NETFLIX_USER=netflix@example.com
NETFLIX_PASS=netflix_password

# Optional
IDLE_TIMEOUT_SECONDS=300  # 5 minutes (default)
IMAP_PORT=993
MAILBOX_NAME=INBOX
MOVE_EMAILS_TO_MAILBOX=true
MOVE_TO_MAILBOX_NAME=Netflix
LOG_LEVEL=INFO
```

**Gmail users:** Generate an [App Password](https://myaccount.google.com/apppasswords) instead of using your account password.

### Usage

```bash
python src/main.py
```

The application will:
1. Connect to your IMAP server
2. Enter IDLE mode (waiting for emails)
3. Detect Netflix household emails instantly
4. Extract verification links
5. Open links in headless browser
6. Click confirmation button
7. Save timing reports to `metrics/`

Press **Ctrl+C** to stop gracefully.

## Advanced Configuration

### Environment Variables Reference

**IMAP Settings:**
- `IMAP_SERVER` - IMAP server address (e.g., `imap.gmail.com`)
- `IMAP_PORT` - IMAP port (default: `993`)
- `IMAP_USER` - Email username
- `IMAP_PASS` - Email password (use App Password for Gmail)

**Netflix Settings:**
- `NETFLIX_USER` - Netflix account email
- `NETFLIX_PASS` - Netflix account password

**Email Filtering:**
- `SENDER_EMAILS` - Comma-separated authorized senders (default: `info@account.netflix.com`)
- `NETFLIX_LINK_PATTERNS` - Comma-separated URL patterns to match

**Performance Tuning:**
- `IDLE_TIMEOUT_SECONDS` - IDLE timeout in seconds (60-1740, default: `300`)
  - Lower = more frequent reconnections, potentially faster Gmail detection
  - Higher = fewer reconnections, lower network overhead
- `POLLING_TIME_IN_SECONDS` - Fallback polling interval if IDLE unsupported (default: `60`)

**Email Management:**
- `MAILBOX_NAME` - Mailbox to monitor (default: `INBOX`)
- `MOVE_EMAILS_TO_MAILBOX` - Move processed emails (default: `true`)
- `MOVE_TO_MAILBOX_NAME` - Destination folder (default: `Netflix`)

**Logging:**
- `LOG_LEVEL` - Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (default: `INFO`)

### Performance Optimization

**Gmail IDLE Delays:**
Gmail's IMAP IDLE has inherent 1-3 minute server-side delays. To optimize:
- Default 5-minute timeout balances reconnection frequency
- Reduce to 3 minutes (`IDLE_TIMEOUT_SECONDS=180`) for slightly faster detection
- Increase to 15 minutes for fewer reconnections in stable environments

**Metrics & Monitoring:**
Timing reports saved to `metrics/verification_YYYYMMDD_HHMMSS_*.txt` include:
- End-to-end time (notification → verification)
- Queue + email processing time
- Browser verification breakdown
- Performance bottleneck analysis

## Testing

Run the comprehensive test suite:

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific test file
pytest tests/test_email_monitor.py -v
```

**Test Coverage:**
- Email monitoring (IMAP IDLE, UID operations)
- Email parsing (sender/subject validation)
- Link extraction (HTML parsing)
- Browser automation (mocked)
- End-to-end flows (mock IMAP server)

## Architecture & Implementation

See [TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md) for complete technical documentation:
- Core components and workflows
- Dual-queue architecture and performance benefits
- Gmail-specific adaptations
- UID-based operations
- Configuration reference

## Security

See [SECURITY.md](SECURITY.md) for security best practices:
- Credential management
- Gmail App Passwords
- Production deployment
- Audit logging

**Never commit credentials to git.** Use `.env` file (excluded by `.gitignore`).

## Troubleshooting

**Gmail not detecting emails:**
- Verify App Password (not account password)
- Check `SENDER_EMAILS` includes authorized senders
- Reduce `IDLE_TIMEOUT_SECONDS` to 180 (3 minutes)
- Check logs for `email_filtered_by_subject` messages

**Subject filtering issues:**
- Email subject must contain exactly: `Important: How to update your Netflix Household`
- Check logs for `email_filtered_by_subject` to see rejected subjects

**Browser automation failures:**
- Ensure Playwright browsers installed: `playwright install chromium`
- Check `metrics/` folder for timing reports with error details
- Verify Netflix credentials are correct

## License

MIT License - See [LICENSE](LICENSE)

---

**Documentation:**
- [TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md) - Architecture & implementation reference
- [SECURITY.md](SECURITY.md) - Security best practices
