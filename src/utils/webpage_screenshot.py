# src/utils/webpage_screenshot.py
"""Capture generic webpage screenshots using Playwright."""

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from src.utils.opencli_browser import capture_screenshot_via_opencli


class WebpageScreenshot:
    """Capture screenshots of generic webpages."""

    def __init__(self):
        self.output_dir = Path("output/webpage_screenshots")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is valid and not a file/media URL."""
        if not url or not url.startswith("http"):
            return False

        parsed = urlparse(url)
        path = parsed.path.lower()

        # Skip file downloads
        skip_extensions = (
            ".pdf", ".zip", ".tar", ".gz", ".rar",
            ".mp4", ".mp3", ".avi", ".mov", ".mkv",
            ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
            ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".exe", ".dmg", ".pkg", ".deb", ".rpm",
        )

        for ext in skip_extensions:
            if path.endswith(ext):
                return False

        return True

    def _get_cache_path(self, url: str) -> Path:
        """Get cache file path for a URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        # Sanitize domain for filename
        parsed = urlparse(url)
        domain = parsed.netloc.replace(".", "_").replace(":", "_")
        return self.output_dir / f"web_{domain}_{url_hash}.png"

    def capture(self, url: str, wait_for_content: bool = True) -> Path | None:
        """Capture a screenshot of a webpage.

        Args:
            url: Webpage URL
            wait_for_content: Whether to wait for dynamic content to load

        Returns:
            Path to screenshot file, or None if failed
        """
        if not self._is_valid_url(url):
            logger.debug(f"Skipping invalid or media URL: {url}")
            return None

        cache_path = self._get_cache_path(url)
        if cache_path.exists():
            logger.debug(f"Using cached screenshot: {cache_path}")
            return cache_path

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = None
                for browser_type in [p.firefox, p.chromium]:
                    try:
                        browser = browser_type.launch(
                            headless=True,
                            args=["--no-sandbox"] if browser_type == p.chromium else [],
                        )
                        logger.debug(f"Launched {browser_type.name} browser")
                        break
                    except Exception as e:
                        logger.debug(f"Failed to launch {browser_type.name}: {e}")
                        continue

                if not browser:
                    logger.error("No browser could be launched")
                    raise RuntimeError("No browser could be launched")

                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )

                page = context.new_page()

                # Navigate to the page
                logger.info(f"Navigating to {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                if wait_for_content:
                    # Wait for common content selectors
                    content_selectors = [
                        "main",
                        "article",
                        ".content",
                        "#content",
                        ".post",
                        ".entry",
                        "[role='main']",
                        "h1",
                    ]

                    for selector in content_selectors:
                        try:
                            page.wait_for_selector(selector, timeout=3000)
                            logger.debug(f"Content loaded: {selector}")
                            break
                        except Exception:
                            continue

                    # Additional wait for dynamic content
                    page.wait_for_timeout(2000)

                # Scroll to capture more content
                page.evaluate("window.scrollTo(0, 400)")
                page.wait_for_timeout(500)

                # Take screenshot
                screenshot_path = str(cache_path)
                page.screenshot(path=screenshot_path, full_page=False)

                context.close()
                browser.close()

                if Path(screenshot_path).exists():
                    logger.info(f"Webpage screenshot saved: {screenshot_path}")
                    return Path(screenshot_path)

        except Exception as e:
            logger.warning(f"Failed to capture webpage screenshot: {e}")

        fallback = capture_screenshot_via_opencli(url, cache_path, full_page=False)
        if fallback:
            return fallback
        return None

    def capture_from_text(self, text: str) -> Path | None:
        """Extract URL from text and capture screenshot."""
        # Find first HTTP URL in text
        url_pattern = r'https?://[^\s<>"\')\]]+(?:/[^\s<>"\')\]]*)?'
        match = re.search(url_pattern, text)
        if match:
            url = match.group(0)
            return self.capture(url)
        return None
