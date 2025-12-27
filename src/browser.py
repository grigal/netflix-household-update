"""Browser automation using Playwright."""

import asyncio
from typing import Optional

import structlog
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Settings

logger = structlog.get_logger(__name__)


class NetflixBrowserAutomation:
    """Handles Netflix website automation using Playwright."""

    def __init__(self, settings: Settings):
        """Initialize browser automation.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    async def initialize(self) -> None:
        """Initialize Playwright and browser."""
        try:
            logger.info("initializing_playwright")
            self.playwright = await async_playwright().start()

            # Launch browser in headless mode
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )

            # Create browser context
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )

            logger.info("playwright_initialized")

        except Exception as e:
            logger.error("playwright_initialization_failed", error=str(e), exc_info=True)
            raise

    async def cleanup(self) -> None:
        """Clean up browser resources."""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("playwright_cleaned_up")
        except Exception as e:
            logger.warning("playwright_cleanup_error", error=str(e))

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def process_verification_link(self, url: str) -> bool:
        """Process Netflix household verification link.

        Args:
            url: Verification URL from email

        Returns:
            True if successful, False otherwise
        """
        if not self.context:
            raise RuntimeError("Browser not initialized")

        page: Optional[Page] = None

        try:
            logger.info("processing_verification_link", url=url)

            # Create new page
            page = await self.context.new_page()

            # Navigate to verification URL
            await page.goto(url, wait_until="networkidle", timeout=30000)

            logger.debug("page_loaded", url=page.url)

            # Check for expired link or error messages
            page_content = await page.content()
            if any(msg in page_content.lower() for msg in ["expired", "invalid", "no longer valid", "link has been used"]):
                logger.warning("verification_link_appears_expired_or_invalid", url=url)
                await page.screenshot(path="debug_expired_link.png")
                logger.info("screenshot_saved", path="debug_expired_link.png")
                return False

            # Check if we need to login
            if await self._is_login_page(page):
                logger.info("login_required")
                success = await self._login_to_netflix(page)

                if not success:
                    logger.error("login_failed")
                    return False

                # Wait for redirect after login
                await page.wait_for_load_state("networkidle", timeout=10000)

            # Click the confirmation button
            success = await self._click_confirmation_button(page)

            if success:
                logger.info("verification_completed", url=url)
            else:
                logger.error("verification_failed", url=url)

            return success

        except Exception as e:
            logger.error(
                "verification_link_processing_failed",
                url=url,
                error=str(e),
                exc_info=True,
            )
            return False

        finally:
            if page:
                await page.close()

    async def _is_login_page(self, page: Page) -> bool:
        """Check if current page is Netflix login page.

        Args:
            page: Playwright page

        Returns:
            True if login page detected
        """
        try:
            # Look for login form elements
            email_field = page.locator('input[name="userLoginId"]')
            return await email_field.count() > 0

        except Exception:
            return False

    async def _login_to_netflix(self, page: Page) -> bool:
        """Login to Netflix account.

        Args:
            page: Playwright page

        Returns:
            True if login successful
        """
        try:
            logger.info("attempting_netflix_login")

            # Check if login form elements are actually present
            email_field = page.locator('input[name="userLoginId"]')
            password_field = page.locator('input[name="password"]')
            login_button = page.locator('button[data-uia="login-submit-button"]')

            # Wait for form elements with timeout
            try:
                await email_field.wait_for(state="visible", timeout=5000)
                await password_field.wait_for(state="visible", timeout=5000)
            except Exception as e:
                logger.error("login_form_not_found", error=str(e))
                # Take screenshot for debugging
                await page.screenshot(path="debug_login_form_not_found.png")
                logger.info("screenshot_saved", path="debug_login_form_not_found.png")
                return False

            # Fill in credentials
            await email_field.fill(self.settings.netflix_user)
            await password_field.fill(self.settings.get_netflix_password())

            # Wait for login button to be clickable
            try:
                await login_button.wait_for(state="visible", timeout=5000)
                await login_button.click()
            except Exception as e:
                logger.error("login_button_not_clickable", error=str(e))
                await page.screenshot(path="debug_login_button_error.png")
                logger.info("screenshot_saved", path="debug_login_button_error.png")
                return False

            # Wait for navigation or error
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
                logger.info("netflix_login_successful")
                return True

            except Exception as e:
                logger.warning("login_navigation_timeout", error=str(e))
                # Check if we're still on login page (login failed)
                if await self._is_login_page(page):
                    logger.error("login_failed_still_on_login_page")
                    return False
                # If not on login page, login probably succeeded
                return True

        except Exception as e:
            logger.error("netflix_login_exception", error=str(e), exc_info=True)
            return False

    async def _click_confirmation_button(self, page: Page) -> bool:
        """Click the household location confirmation button.

        Args:
            page: Playwright page

        Returns:
            True if button clicked successfully
        """
        try:
            logger.info("searching_for_confirmation_button")

            # Build selector for confirmation button
            selector = (
                f'button[{self.settings.button_search_attr_name}='
                f'"{self.settings.button_search_attr_value}"]'
            )

            # Wait for button to appear
            button = page.locator(selector)

            # Wait up to 10 seconds for button
            await button.wait_for(state="visible", timeout=10000)

            # Click the button
            await button.click()

            logger.info("confirmation_button_clicked")

            # Wait a moment for action to complete
            await asyncio.sleep(2)

            return True

        except Exception as e:
            logger.error(
                "confirmation_button_not_found_or_click_failed",
                error=str(e),
                exc_info=True,
            )
            return False


class BrowserPool:
    """Manages a pool of browser instances for concurrent processing."""

    def __init__(self, settings: Settings, pool_size: int = 1):
        """Initialize browser pool.

        Args:
            settings: Application settings
            pool_size: Number of browser instances to maintain
        """
        self.settings = settings
        self.pool_size = pool_size
        self.browsers: list[NetflixBrowserAutomation] = []
        self._semaphore = asyncio.Semaphore(pool_size)

    async def initialize(self) -> None:
        """Initialize browser pool."""
        logger.info("initializing_browser_pool", size=self.pool_size)

        for i in range(self.pool_size):
            browser = NetflixBrowserAutomation(self.settings)
            await browser.initialize()
            self.browsers.append(browser)

        logger.info("browser_pool_initialized")

    async def cleanup(self) -> None:
        """Clean up all browsers in pool."""
        logger.info("cleaning_up_browser_pool")

        for browser in self.browsers:
            await browser.cleanup()

        self.browsers.clear()

    async def process_link(self, url: str) -> bool:
        """Process verification link using available browser from pool.

        Args:
            url: Verification URL

        Returns:
            True if successful
        """
        async with self._semaphore:
            # Use first available browser (simple round-robin)
            browser = self.browsers[0] if self.browsers else None

            if not browser:
                logger.error("no_browser_available")
                return False

            return await browser.process_verification_link(url)
