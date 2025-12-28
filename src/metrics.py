"""Performance metrics and profiling for the Netflix household updater.

This module tracks timing and resource usage for all major operations,
allowing performance analysis and bottleneck identification.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class OperationMetrics:
    """Metrics for a single operation."""

    name: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    success: bool = True
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def finish(self, success: bool = True, error: Optional[str] = None):
        """Mark operation as finished and calculate duration."""
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        self.success = success
        self.error = error


class MetricsCollector:
    """Collects and aggregates performance metrics."""

    def __init__(self):
        """Initialize metrics collector."""
        self.operations: list[OperationMetrics] = []
        self.start_time = time.time()

        # Aggregate counters
        self.idle_detections = 0
        self.emails_processed = 0
        self.links_processed = 0
        self.verifications_success = 0
        self.verifications_failed = 0

        # Timing aggregates
        self.idle_pause_times: list[float] = []
        self.email_fetch_times: list[float] = []
        self.email_parse_times: list[float] = []
        self.verification_times: list[float] = []

        # Queue depth tracking
        self.email_queue_depths: list[tuple[float, int]] = []  # (timestamp, depth)
        self.link_queue_depths: list[tuple[float, int]] = []

    def start_operation(self, name: str, **metadata) -> OperationMetrics:
        """Start tracking an operation.

        Args:
            name: Operation name (e.g., "idle_detection", "email_fetch")
            **metadata: Additional metadata to attach

        Returns:
            OperationMetrics object to finish later
        """
        op = OperationMetrics(
            name=name,
            start_time=time.time(),
            metadata=metadata
        )
        self.operations.append(op)
        return op

    def record_idle_pause(self, duration: float):
        """Record how long IDLE was paused."""
        self.idle_pause_times.append(duration)

    def record_email_fetch(self, duration: float):
        """Record email fetch duration."""
        self.email_fetch_times.append(duration)
        self.emails_processed += 1

    def record_email_parse(self, duration: float):
        """Record email parsing duration."""
        self.email_parse_times.append(duration)

    def record_verification(self, duration: float, success: bool):
        """Record verification duration and result."""
        self.verification_times.append(duration)
        self.links_processed += 1
        if success:
            self.verifications_success += 1
        else:
            self.verifications_failed += 1

    def record_queue_depth(self, queue_name: str, depth: int):
        """Record queue depth at current time."""
        timestamp = time.time() - self.start_time
        if queue_name == "email":
            self.email_queue_depths.append((timestamp, depth))
        elif queue_name == "link":
            self.link_queue_depths.append((timestamp, depth))

    def get_summary(self) -> dict:
        """Get summary statistics of all metrics.

        Returns:
            Dictionary with aggregated metrics
        """
        total_runtime = time.time() - self.start_time

        return {
            "runtime": {
                "total_seconds": round(total_runtime, 2),
                "total_minutes": round(total_runtime / 60, 2),
            },
            "operations": {
                "total_operations": len(self.operations),
                "idle_detections": self.idle_detections,
                "emails_processed": self.emails_processed,
                "links_processed": self.links_processed,
            },
            "verification_results": {
                "success": self.verifications_success,
                "failed": self.verifications_failed,
                "success_rate": (
                    round(self.verifications_success / max(self.links_processed, 1) * 100, 1)
                    if self.links_processed > 0 else 0
                ),
            },
            "timing": {
                "idle_pause": self._get_timing_stats(self.idle_pause_times),
                "email_fetch": self._get_timing_stats(self.email_fetch_times),
                "email_parse": self._get_timing_stats(self.email_parse_times),
                "verification": self._get_timing_stats(self.verification_times),
            },
            "queues": {
                "email_queue": {
                    "max_depth": max((d for _, d in self.email_queue_depths), default=0),
                    "avg_depth": (
                        round(sum(d for _, d in self.email_queue_depths) / len(self.email_queue_depths), 2)
                        if self.email_queue_depths else 0
                    ),
                },
                "link_queue": {
                    "max_depth": max((d for _, d in self.link_queue_depths), default=0),
                    "avg_depth": (
                        round(sum(d for _, d in self.link_queue_depths) / len(self.link_queue_depths), 2)
                        if self.link_queue_depths else 0
                    ),
                },
            },
        }

    def _get_timing_stats(self, times: list[float]) -> dict:
        """Calculate timing statistics.

        Args:
            times: List of durations in seconds

        Returns:
            Dictionary with min, max, avg, total
        """
        if not times:
            return {
                "count": 0,
                "min_seconds": 0,
                "max_seconds": 0,
                "avg_seconds": 0,
                "total_seconds": 0,
            }

        return {
            "count": len(times),
            "min_seconds": round(min(times), 3),
            "max_seconds": round(max(times), 3),
            "avg_seconds": round(sum(times) / len(times), 3),
            "total_seconds": round(sum(times), 2),
        }

    def print_summary(self):
        """Print formatted summary to console."""
        summary = self.get_summary()

        print("\n" + "="*70)
        print("PERFORMANCE METRICS SUMMARY")
        print("="*70)

        print(f"\n[RUNTIME] {summary['runtime']['total_seconds']}s ({summary['runtime']['total_minutes']}min)")

        print(f"\n[OPERATIONS]")
        print(f"   - IDLE detections: {summary['operations']['idle_detections']}")
        print(f"   - Emails processed: {summary['operations']['emails_processed']}")
        print(f"   - Links processed: {summary['operations']['links_processed']}")

        print(f"\n[RESULTS]")
        print(f"   - Success: {summary['verification_results']['success']}")
        print(f"   - Failed: {summary['verification_results']['failed']}")
        print(f"   - Success rate: {summary['verification_results']['success_rate']}%")

        print(f"\n[TIMING ANALYSIS]")

        if summary['timing']['idle_pause']['count'] > 0:
            t = summary['timing']['idle_pause']
            print(f"   IDLE Pause Duration:")
            print(f"      Min: {t['min_seconds']}s | Max: {t['max_seconds']}s | Avg: {t['avg_seconds']}s")

        if summary['timing']['email_fetch']['count'] > 0:
            t = summary['timing']['email_fetch']
            print(f"   Email Fetch:")
            print(f"      Min: {t['min_seconds']}s | Max: {t['max_seconds']}s | Avg: {t['avg_seconds']}s")
            print(f"      Total: {t['total_seconds']}s across {t['count']} emails")

        if summary['timing']['email_parse']['count'] > 0:
            t = summary['timing']['email_parse']
            print(f"   Email Parse:")
            print(f"      Min: {t['min_seconds']}s | Max: {t['max_seconds']}s | Avg: {t['avg_seconds']}s")

        if summary['timing']['verification']['count'] > 0:
            t = summary['timing']['verification']
            print(f"   Verification (Browser):")
            print(f"      Min: {t['min_seconds']}s | Max: {t['max_seconds']}s | Avg: {t['avg_seconds']}s")
            print(f"      Total: {t['total_seconds']}s across {t['count']} verifications")

        print(f"\n[QUEUE DEPTHS]")
        print(f"   Email Queue: Max={summary['queues']['email_queue']['max_depth']}, Avg={summary['queues']['email_queue']['avg_depth']}")
        print(f"   Link Queue: Max={summary['queues']['link_queue']['max_depth']}, Avg={summary['queues']['link_queue']['avg_depth']}")

        # Bottleneck analysis
        print(f"\n[BOTTLENECK ANALYSIS]")
        timing = summary['timing']

        total_email_time = timing['email_fetch']['total_seconds'] + timing['email_parse']['total_seconds']
        total_verification_time = timing['verification']['total_seconds']

        if total_email_time > 0 or total_verification_time > 0:
            email_pct = (total_email_time / (total_email_time + total_verification_time)) * 100
            verification_pct = (total_verification_time / (total_email_time + total_verification_time)) * 100

            print(f"   Email Processing: {round(total_email_time, 1)}s ({round(email_pct, 1)}%)")
            print(f"   Verification: {round(total_verification_time, 1)}s ({round(verification_pct, 1)}%)")

            if verification_pct > 80:
                print(f"\n   [!] Bottleneck: Browser verification is the slowest operation")
                print(f"       Consider adding more link workers for parallel processing")
            elif email_pct > 50:
                print(f"\n   [!] Bottleneck: Email processing is taking significant time")
                print(f"       Email fetching/parsing could be optimized")

        print("\n" + "="*70 + "\n")

    def log_summary(self):
        """Log summary as structured log for monitoring."""
        summary = self.get_summary()
        logger.info("metrics_summary", **summary)


# Global metrics collector instance
_metrics: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """Get or create global metrics collector."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def reset_metrics():
    """Reset global metrics collector."""
    global _metrics
    _metrics = MetricsCollector()
