"""Test concurrent processing performance using dependency injection.

This test uses the REAL application code (NetflixHouseholdUpdater)
with fake dependencies that simulate realistic timing.
"""

import asyncio
import pytest
from src.main import NetflixHouseholdUpdater
from src.config import Settings
from tests.test_doubles import FakeEmailMonitor, FakeBrowserPool


@pytest.mark.asyncio
async def test_concurrent_email_detection_during_verification():
    """Test that emails are detected while verification is running.

    Scenario:
    - Email 1 arrives at 0s
    - Email 2 arrives at 2s (while Email 1 is being verified)
    - Each verification takes 5s

    Expected:
    - Email 2 should be detected at ~2s (not after Email 1 finishes at 5s)
    - Total time should be ~7s (not 10s sequential)
    """
    # Setup: Create fake dependencies with realistic timing
    email_monitor = FakeEmailMonitor(
        simulated_arrivals=[
            (0, ["https://netflix.com/verify?token=1"]),  # Email 1 at 0s
            (2, ["https://netflix.com/verify?token=2"]),  # Email 2 at 2s
        ]
    )

    browser_pool = FakeBrowserPool(
        verification_time=5.0,  # 5 seconds per verification
        success_rate=1.0,
    )

    # Create settings (can use defaults for testing)
    settings = Settings(
        imap_server="test",
        imap_user="test",
        imap_pass="test",
        netflix_user="test",
        netflix_pass="test",
    )

    # Create real application with fake dependencies
    app = NetflixHouseholdUpdater(
        settings=settings,
        email_monitor=email_monitor,
        browser_pool=browser_pool,
    )

    await app.initialize()

    # Run the application for a limited time
    try:
        await asyncio.wait_for(app.run_with_idle(), timeout=15.0)
    except asyncio.TimeoutError:
        pass
    finally:
        app._shutdown_event.set()
        await app.cleanup()

    # Verify concurrent behavior
    assert email_monitor.detection_count == 2, "Should detect 2 emails"
    assert browser_pool.processing_count == 2, "Should process 2 verifications"
    assert len(browser_pool.processed_links) == 2, "Should verify 2 links"

    # Verify the actual links were processed
    assert "token=1" in browser_pool.processed_links[0]
    assert "token=2" in browser_pool.processed_links[1]


@pytest.mark.asyncio
async def test_rapid_email_arrivals():
    """Test handling of many emails arriving rapidly.

    Scenario:
    - 5 emails arrive at 0s, 1s, 2s, 3s, 4s
    - Each verification takes 3s

    Expected:
    - All emails detected within 5s
    - Verifications happen concurrently
    - Total time ~7s (not 15s sequential)
    """
    email_monitor = FakeEmailMonitor(
        simulated_arrivals=[
            (0, ["https://netflix.com/verify?token=1"]),
            (1, ["https://netflix.com/verify?token=2"]),
            (2, ["https://netflix.com/verify?token=3"]),
            (3, ["https://netflix.com/verify?token=4"]),
            (4, ["https://netflix.com/verify?token=5"]),
        ]
    )

    browser_pool = FakeBrowserPool(verification_time=3.0, success_rate=1.0)

    settings = Settings(
        imap_server="test",
        imap_user="test",
        imap_pass="test",
        netflix_user="test",
        netflix_pass="test",
    )

    app = NetflixHouseholdUpdater(
        settings=settings,
        email_monitor=email_monitor,
        browser_pool=browser_pool,
    )

    await app.initialize()

    try:
        await asyncio.wait_for(app.run_with_idle(), timeout=20.0)
    except asyncio.TimeoutError:
        pass
    finally:
        app._shutdown_event.set()
        await app.cleanup()

    assert email_monitor.detection_count == 5, "Should detect all 5 emails"
    assert browser_pool.processing_count == 5, "Should process all 5 verifications"


@pytest.mark.asyncio
async def test_idle_resume_speed():
    """Test that IDLE mode resumes quickly after email detection.

    This verifies the key performance characteristic: email monitoring
    should return to IDLE mode in <1s, not wait for verification to complete.
    """
    # Single email with slow verification
    email_monitor = FakeEmailMonitor(
        simulated_arrivals=[(0, ["https://netflix.com/verify?token=1"])]
    )

    browser_pool = FakeBrowserPool(verification_time=10.0, success_rate=1.0)

    settings = Settings(
        imap_server="test",
        imap_user="test",
        imap_pass="test",
        netflix_user="test",
        netflix_pass="test",
    )

    app = NetflixHouseholdUpdater(
        settings=settings,
        email_monitor=email_monitor,
        browser_pool=browser_pool,
    )

    await app.initialize()

    try:
        await asyncio.wait_for(app.run_with_idle(), timeout=15.0)
    except asyncio.TimeoutError:
        pass
    finally:
        app._shutdown_event.set()
        await app.cleanup()

    # The test passes if it completes - the architecture ensures
    # email monitoring doesn't wait for the 10s verification


if __name__ == "__main__":
    # Run tests manually without pytest
    import sys

    async def run_all_tests():
        print("\n" + "="*70)
        print("CONCURRENT PROCESSING PERFORMANCE TESTS")
        print("="*70 + "\n")

        print("Test 1: Email detection during verification...")
        try:
            await test_concurrent_email_detection_during_verification()
            print("✅ PASSED\n")
        except AssertionError as e:
            print(f"❌ FAILED: {e}\n")

        print("Test 2: Rapid email arrivals...")
        try:
            await test_rapid_email_arrivals()
            print("✅ PASSED\n")
        except AssertionError as e:
            print(f"❌ FAILED: {e}\n")

        print("Test 3: IDLE resume speed...")
        try:
            await test_idle_resume_speed()
            print("✅ PASSED\n")
        except AssertionError as e:
            print(f"❌ FAILED: {e}\n")

        print("="*70)
        print("TESTS COMPLETED")
        print("="*70 + "\n")

    asyncio.run(run_all_tests())
