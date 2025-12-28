"""Test doubles (fakes, mocks, stubs) for testing.

These implementations follow the same protocols as production code
but use controllable, fast, in-memory behavior.
"""

import asyncio
from typing import AsyncIterator


class FakeEmailMonitor:
    """Fake email monitor that simulates real behavior with controlled timing.

    This uses REAL data (actual email arrival times, real links) but
    doesn't require actual IMAP connections.
    """

    def __init__(self, simulated_arrivals: list[tuple[float, list[str]]]):
        """Initialize with simulated email arrivals.

        Args:
            simulated_arrivals: List of (time_seconds, links) tuples
                Example: [(0, ["link1"]), (5, ["link2", "link3"])]
        """
        self.simulated_arrivals = simulated_arrivals
        self.start_time = None
        self._running = True
        self.detection_count = 0
        self.processing_count = 0

    async def connect(self):
        """Mock connection."""
        pass

    async def disconnect(self):
        """Mock disconnection."""
        pass

    async def initialize(self):
        """Mock initialization."""
        pass

    async def cleanup(self):
        """Mock cleanup."""
        pass

    def stop(self):
        """Stop monitoring."""
        self._running = False

    async def monitor_idle_notifications(self) -> AsyncIterator[int]:
        """Simulate IDLE notifications at specific times, yielding email IDs."""
        if self.start_time is None:
            import time
            self.start_time = time.time()

        email_id = 1
        for arrival_time, _links in self.simulated_arrivals:
            if not self._running:
                break

            # Wait until email should arrive
            import time
            elapsed = time.time() - self.start_time
            wait_time = arrival_time - elapsed

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            self.detection_count += 1
            yield str(email_id)
            email_id += 1

    async def process_email_by_id(self, email_id: str) -> str | None:
        """Process a specific email by ID and return its link."""
        # Simulate email processing time
        await asyncio.sleep(0.5)

        # Map email_id to arrival index (1-based to 0-based)
        index = int(email_id) - 1
        if 0 <= index < len(self.simulated_arrivals):
            _time, links = self.simulated_arrivals[index]
            self.processing_count += 1
            return links[0] if links else None

        return None

    async def process_emails(self) -> list[str]:
        """Return the links for the current email arrival."""
        # Simulate email processing time
        await asyncio.sleep(0.5)

        # Find which arrival we're on
        if self.processing_count < len(self.simulated_arrivals):
            _time, links = self.simulated_arrivals[self.processing_count]
            self.processing_count += 1
            return links

        return []


class FakeBrowserPool:
    """Fake browser pool that simulates verification with controllable timing.

    This tracks actual verification calls with real links but doesn't
    require actual browser automation.
    """

    def __init__(self, verification_time: float = 1.0, success_rate: float = 1.0):
        """Initialize fake browser pool.

        Args:
            verification_time: Seconds to simulate per verification
            success_rate: Fraction of verifications that succeed (0.0-1.0)
        """
        self.verification_time = verification_time
        self.success_rate = success_rate
        self.processed_links = []
        self.processing_count = 0

    async def initialize(self):
        """Mock initialization."""
        pass

    async def cleanup(self):
        """Mock cleanup."""
        pass

    async def process_link(self, link: str) -> bool:
        """Simulate processing a verification link."""
        self.processing_count += 1

        # Simulate browser automation time
        await asyncio.sleep(self.verification_time)

        # Track the link
        self.processed_links.append(link)

        # Simulate success/failure based on success_rate
        import random
        success = random.random() < self.success_rate

        return success


class RecordingEmailMonitor:
    """Email monitor that records all method calls with real data.

    This wraps a real EmailMonitor and records timing/calls for analysis.
    """

    def __init__(self, real_monitor):
        """Wrap a real email monitor.

        Args:
            real_monitor: Actual EmailMonitor instance
        """
        self.real_monitor = real_monitor
        self.idle_enter_times = []
        self.idle_exit_times = []
        self.process_times = []

    async def connect(self):
        """Delegate to real monitor."""
        return await self.real_monitor.connect()

    async def disconnect(self):
        """Delegate to real monitor."""
        return await self.real_monitor.disconnect()

    async def initialize(self):
        """Delegate to real monitor."""
        if hasattr(self.real_monitor, 'initialize'):
            return await self.real_monitor.initialize()

    async def cleanup(self):
        """Delegate to real monitor."""
        if hasattr(self.real_monitor, 'cleanup'):
            return await self.real_monitor.cleanup()

    def stop(self):
        """Delegate to real monitor."""
        return self.real_monitor.stop()

    async def monitor_idle_notifications(self) -> AsyncIterator[bool]:
        """Record timing and delegate to real monitor."""
        import time

        async for notification in self.real_monitor.monitor_idle_notifications():
            self.idle_exit_times.append(time.time())
            yield notification
            self.idle_enter_times.append(time.time())

    async def process_emails(self) -> list[str]:
        """Record timing and delegate to real monitor."""
        import time
        start = time.time()

        result = await self.real_monitor.process_emails()

        end = time.time()
        self.process_times.append((start, end))

        return result

    def get_idle_pause_durations(self) -> list[float]:
        """Get list of how long IDLE was paused each time."""
        durations = []
        for i in range(min(len(self.idle_exit_times), len(self.idle_enter_times))):
            duration = self.idle_enter_times[i] - self.idle_exit_times[i]
            durations.append(duration)
        return durations


class RecordingBrowserPool:
    """Browser pool that records all verification calls with timing.

    This wraps a real BrowserPool and records what happened.
    """

    def __init__(self, real_pool):
        """Wrap a real browser pool.

        Args:
            real_pool: Actual BrowserPool instance
        """
        self.real_pool = real_pool
        self.verification_start_times = []
        self.verification_end_times = []
        self.verification_links = []
        self.verification_results = []

    async def initialize(self):
        """Delegate to real pool."""
        return await self.real_pool.initialize()

    async def cleanup(self):
        """Delegate to real pool."""
        return await self.real_pool.cleanup()

    async def process_link(self, link: str) -> bool:
        """Record timing and delegate to real pool."""
        import time
        start = time.time()
        self.verification_start_times.append(start)
        self.verification_links.append(link)

        result = await self.real_pool.process_link(link)

        end = time.time()
        self.verification_end_times.append(end)
        self.verification_results.append(result)

        return result

    def get_concurrent_verifications(self) -> int:
        """Count how many verifications ran concurrently."""
        concurrent_count = 0

        for i in range(len(self.verification_start_times) - 1):
            start = self.verification_start_times[i]
            end = self.verification_end_times[i]

            # Check if next verification started before this one ended
            for j in range(i + 1, len(self.verification_start_times)):
                next_start = self.verification_start_times[j]
                if next_start < end:
                    concurrent_count += 1
                else:
                    break

        return concurrent_count
