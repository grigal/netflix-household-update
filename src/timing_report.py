"""Timing report generation for verification performance tracking.

Generates human-readable timing reports after each verification,
saved to timestamped files for historical analysis.

This module uses a structlog processor to listen for verification timing
events and automatically generate reports without polluting browser code.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class TimingReportProcessor:
    """Structlog processor that generates timing reports from log events.

    Listens for 'verification_timing_breakdown' and 'verification_completed'
    events and automatically saves human-readable timing reports.
    """

    def __init__(self, output_dir: str = "metrics"):
        """Initialize the processor.

        Args:
            output_dir: Directory to save timing reports
        """
        self.output_dir = output_dir
        self._pending_timings = {}  # Store timing data by URL

    def __call__(self, logger, method_name, event_dict):
        """Process log events and generate reports when appropriate.

        Args:
            logger: The logger instance
            method_name: The logging method name
            event_dict: Dictionary containing the log event data

        Returns:
            The event_dict unchanged (pass-through processor)
        """
        event = event_dict.get("event")

        # Capture timing breakdown
        if event == "verification_timing_breakdown":
            url = event_dict.get("url", "unknown")
            self._pending_timings[url] = {
                "total": event_dict.get("total_seconds", 0),
                "create_page": event_dict.get("create_page_seconds", 0),
                "page_load": event_dict.get("page_load_seconds", 0),
                "error_check": event_dict.get("error_check_seconds", 0),
                "login_check": event_dict.get("login_check_seconds", 0),
                "login_process": event_dict.get("login_process_seconds", 0),
                "post_login_wait": event_dict.get("post_login_wait_seconds", 0),
                "click_confirmation": event_dict.get("click_confirmation_seconds", 0),
            }

        # Generate report when verification completes successfully
        elif event == "verification_completed":
            url = event_dict.get("url", "unknown")
            if url in self._pending_timings:
                timings = self._pending_timings.pop(url)
                self._save_report(success=True, timings=timings, link=url)

        # Also generate report on failure
        elif event == "verification_failed":
            url = event_dict.get("url", "unknown")
            if url in self._pending_timings:
                timings = self._pending_timings.pop(url)
                self._save_report(success=False, timings=timings, link=url)

        return event_dict

    def _save_report(self, success: bool, timings: dict, link: str):
        """Save timing report to file."""
        save_verification_timing_report(
            success=success,
            timings=timings,
            link=link,
            output_dir=self.output_dir
        )


def save_verification_timing_report(
    success: bool,
    timings: dict,
    link: str,
    output_dir: str = "metrics"
) -> Optional[Path]:
    """Save verification timing report to a timestamped file.

    Args:
        success: Whether verification succeeded
        timings: Dictionary of timing data from browser verification
        link: Verification link (will be redacted in report)
        output_dir: Directory to save reports (default: "metrics")

    Returns:
        Path to saved report file, or None if save failed
    """
    try:
        # Create output directory
        metrics_dir = Path(output_dir)
        metrics_dir.mkdir(exist_ok=True)

        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"verification_{timestamp}.txt"
        filepath = metrics_dir / filename

        # Redact link for privacy (show only last 10 chars)
        redacted_link = "..." + link[-10:] if len(link) > 10 else "***"

        # Build human-readable report
        report_lines = [
            "=" * 70,
            "VERIFICATION TIMING REPORT",
            "=" * 70,
            "",
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Result: {'SUCCESS' if success else 'FAILED'}",
            f"Link: {redacted_link}",
            "",
            "=" * 70,
            "TIMING BREAKDOWN",
            "=" * 70,
            "",
        ]

        # Add detailed timing breakdown
        if "total" in timings:
            report_lines.append(f"Total Time: {timings['total']:.3f}s")
            report_lines.append("")

        report_lines.append("Step-by-Step Breakdown:")
        report_lines.append("")

        # Browser pool timing (if available)
        if "semaphore_wait" in timings:
            report_lines.append(f"  [Pool] Semaphore Wait:     {timings['semaphore_wait']:.3f}s")

        # Page operations
        if "create_page" in timings:
            report_lines.append(f"  [1] Create Page:           {timings['create_page']:.3f}s")
        if "page_load" in timings:
            report_lines.append(f"  [2] Page Load:             {timings['page_load']:.3f}s")
        if "error_check" in timings:
            report_lines.append(f"  [3] Error Check:           {timings['error_check']:.3f}s")
        if "login_check" in timings:
            report_lines.append(f"  [4] Login Check:           {timings['login_check']:.3f}s")

        # Login process (if occurred)
        if "login_process" in timings and timings["login_process"] > 0:
            report_lines.append(f"  [5] Login Process:         {timings['login_process']:.3f}s")
            if "post_login_wait" in timings:
                report_lines.append(f"  [6] Post-Login Wait:       {timings['post_login_wait']:.3f}s")

        # Confirmation
        if "click_confirmation" in timings:
            report_lines.append(f"  [7] Click Confirmation:    {timings['click_confirmation']:.3f}s")

        report_lines.append("")
        report_lines.append("=" * 70)
        report_lines.append("PERFORMANCE ANALYSIS")
        report_lines.append("=" * 70)
        report_lines.append("")

        # Calculate percentages
        total = timings.get("total", 0)
        if total > 0:
            page_load_pct = (timings.get("page_load", 0) / total) * 100
            login_pct = (timings.get("login_process", 0) / total) * 100
            click_pct = (timings.get("click_confirmation", 0) / total) * 100

            report_lines.append(f"Page Load:        {page_load_pct:5.1f}% of total time")
            if login_pct > 0:
                report_lines.append(f"Login Process:    {login_pct:5.1f}% of total time")
            report_lines.append(f"Click Confirm:    {click_pct:5.1f}% of total time")
            report_lines.append("")

            # Identify bottleneck
            if page_load_pct > 50:
                report_lines.append("[BOTTLENECK] Page load is the slowest operation")
                report_lines.append("             Consider network optimization or CDN")
            elif login_pct > 30:
                report_lines.append("[BOTTLENECK] Login process is taking significant time")
                report_lines.append("             Netflix server response or form interaction slow")
            elif click_pct > 20:
                report_lines.append("[BOTTLENECK] Confirmation button interaction slow")
                report_lines.append("             Check button selector or page responsiveness")

        report_lines.append("")
        report_lines.append("=" * 70)
        report_lines.append("")

        # Write report to file
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))

        return filepath

    except Exception as e:
        # Log error but don't fail the verification
        print(f"Warning: Failed to save timing report: {e}")
        return None


def save_json_timing_data(
    success: bool,
    timings: dict,
    link: str,
    output_dir: str = "metrics"
) -> Optional[Path]:
    """Save timing data as JSON for programmatic analysis.

    Args:
        success: Whether verification succeeded
        timings: Dictionary of timing data
        link: Verification link (will be redacted)
        output_dir: Directory to save reports

    Returns:
        Path to saved JSON file, or None if save failed
    """
    try:
        # Create output directory
        metrics_dir = Path(output_dir)
        metrics_dir.mkdir(exist_ok=True)

        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"verification_{timestamp}.json"
        filepath = metrics_dir / filename

        # Redact link
        redacted_link = "..." + link[-10:] if len(link) > 10 else "***"

        # Build JSON data
        data = {
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "link": redacted_link,
            "timings": timings,
        }

        # Write JSON
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return filepath

    except Exception as e:
        print(f"Warning: Failed to save JSON timing data: {e}")
        return None
