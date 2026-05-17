# src/utils/reddit_screenshot.py
"""Capture Reddit post screenshots using Playwright."""

import hashlib
import re
from pathlib import Path

from loguru import logger

from src.utils.opencli_browser import capture_screenshot_via_opencli


class RedditScreenshot:
    """Capture screenshots of Reddit posts and comments."""

    def __init__(self):
        self.output_dir = Path("output/reddit_screenshots")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _extract_reddit_url(self, text: str) -> str | None:
        """Extract Reddit URL from text."""
        patterns = [
            r'https?://(?:www\.)?reddit\.com/r/[^/\s]+/comments/\w+[^\s]*',
            r'https?://(?:www\.)?reddit\.com/r/[^/\s]+/s/\w+',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None

    def _get_cache_path(self, url: str) -> Path:
        """Get cache file path for a URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        return self.output_dir / f"reddit_{url_hash}.png"

    def capture(self, post_url: str) -> Path | None:
        """Capture a screenshot of a Reddit post.

        Args:
            post_url: Reddit post URL

        Returns:
            Path to screenshot file, or None if failed
        """
        cache_path = self._get_cache_path(post_url)
        if cache_path.exists():
            logger.debug(f"Using cached screenshot: {cache_path}")
            return cache_path

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                # Try Firefox first (more stable on Linux), fallback to Chromium
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
                    locale="en-US",
                    timezone_id="America/New_York",
                )

                page = context.new_page()

                # Add cookies to bypass some restrictions
                context.add_cookies([
                    {"name": "over18", "value": "1", "domain": ".reddit.com", "path": "/"},
                    {"name": "reddit_session", "value": "", "domain": ".reddit.com", "path": "/"},
                ])

                page.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Upgrade-Insecure-Requests": "1",
                    "Cache-Control": "no-cache",
                })

                logger.info(f"Capturing Reddit screenshot: {post_url}")

                # Navigate to Reddit post
                try:
                    # Use old.reddit.com which is more accessible and has simpler HTML
                    old_reddit_url = post_url.replace("www.reddit.com", "old.reddit.com")
                    if "old.reddit.com" not in post_url:
                        post_url = old_reddit_url

                    response = page.goto(post_url, wait_until="networkidle", timeout=30000)
                    if response and response.status < 400:
                        # Wait for content to load
                        page.wait_for_timeout(3000)

                        # Try to find post content on old.reddit.com
                        post_selectors = [
                            "#siteTable .thing",  # old.reddit.com post container
                            ".thing.id-t3_",      # post with ID
                            "div.link",           # link post
                            "#siteTable",         # main content table
                        ]
                        for selector in post_selectors:
                            try:
                                page.wait_for_selector(selector, timeout=5000)
                                post = page.query_selector(selector)
                                if post:
                                    post.screenshot(path=str(cache_path))
                                    browser.close()
                                    logger.info(f"Reddit screenshot saved: {cache_path}")
                                    return cache_path
                            except:
                                continue

                        # Fallback: screenshot the whole page
                        logger.warning(f"Post element not found, capturing full page: {post_url}")
                        page.screenshot(path=str(cache_path), full_page=False)
                        browser.close()
                        return cache_path
                    else:
                        logger.warning(f"Reddit returned status {response.status if response else 'None'}")
                        browser.close()
                        raise RuntimeError(f"Reddit returned status {response.status if response else 'None'}")
                except Exception as e:
                    logger.warning(f"Reddit capture failed: {e}")
                    browser.close()
                    raise

        except Exception as e:
            logger.warning(f"Failed to capture Reddit screenshot: {e}")
            fallback = capture_screenshot_via_opencli(post_url, cache_path, full_page=False)
            if fallback:
                return fallback
            return None

    def capture_from_text(self, text: str) -> Path | None:
        """Extract Reddit URL from text and capture screenshot.

        Args:
            text: Text containing Reddit URL

        Returns:
            Path to screenshot file, or None if no URL found or capture failed
        """
        url = self._extract_reddit_url(text)
        if not url:
            return None
        return self.capture(url)
