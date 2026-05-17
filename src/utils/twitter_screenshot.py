# src/utils/twitter_screenshot.py
"""Capture Twitter/X screenshots using Playwright."""

import hashlib
import re
from pathlib import Path

from loguru import logger

from src.utils.opencli_browser import capture_screenshot_via_opencli


class TwitterScreenshot:
    """Capture screenshots of Twitter/X posts."""

    def __init__(self):
        self.output_dir = Path("output/twitter_screenshots")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _extract_tweet_url(self, text: str) -> str | None:
        """Extract Twitter/X URL from text."""
        patterns = [
            r'https?://(?:twitter\.com|x\.com)/[^/\s]+/status/\d+',
            r'https?://(?:twitter\.com|x\.com)/[^/\s]+/\d+',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None

    def _get_cache_path(self, url: str) -> Path:
        """Get cache file path for a URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        return self.output_dir / f"tweet_{url_hash}.png"

    def capture(self, tweet_url: str) -> Path | None:
        """Capture a screenshot of a tweet.

        Args:
            tweet_url: Twitter/X tweet URL

        Returns:
            Path to screenshot file, or None if failed
        """
        # Normalize URL
        tweet_url = tweet_url.replace("twitter.com", "x.com")

        cache_path = self._get_cache_path(tweet_url)
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
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    locale="en-US",
                    timezone_id="America/New_York",
                )

                # Set extra headers to appear more like a real browser
                page = context.new_page()
                page.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Upgrade-Insecure-Requests": "1",
                })

                # Navigate to tweet with timeout
                logger.info(f"Capturing screenshot: {tweet_url}")

                # Try nitter mirror first (no login required)
                nitter_url = tweet_url.replace("x.com", "nitter.net")
                try:
                    response = page.goto(nitter_url, wait_until="domcontentloaded", timeout=15000)
                    if response and response.status < 400:
                        # Wait for content
                        page.wait_for_timeout(3000)

                        # Try to find tweet content on nitter
                        tweet_selectors = [
                            ".timeline-item",
                            ".main-tweet",
                            "article",
                        ]
                        for selector in tweet_selectors:
                            try:
                                page.wait_for_selector(selector, timeout=5000)
                                tweet = page.query_selector(selector)
                                if tweet:
                                    tweet.screenshot(path=str(cache_path))
                                    browser.close()
                                    logger.info(f"Screenshot saved via nitter: {cache_path}")
                                    return cache_path
                            except:
                                continue
                        raise RuntimeError(f"Tweet content not found on nitter: {tweet_url}")
                except Exception as e:
                    logger.debug(f"Nitter fallback failed: {e}")

                # Fallback: try direct x.com with longer wait
                try:
                    page.goto(tweet_url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(5000)  # Wait for JS to render

                    # Wait for tweet content with multiple selectors
                    tweet_selectors = [
                        "article[data-testid='tweet']",
                        "[data-testid='tweet']",
                        "article",
                    ]

                    tweet = None
                    for selector in tweet_selectors:
                        try:
                            page.wait_for_selector(selector, timeout=5000)
                            tweet = page.query_selector(selector)
                            if tweet:
                                break
                        except:
                            continue

                    if not tweet:
                        # Fallback: screenshot the whole page
                        logger.warning(f"Tweet element not found, capturing full page: {tweet_url}")
                        page.screenshot(path=str(cache_path), full_page=False)
                        browser.close()
                        return cache_path

                    # Take screenshot of just the tweet
                    tweet.screenshot(path=str(cache_path))
                    browser.close()

                    logger.info(f"Screenshot saved: {cache_path}")
                    return cache_path
                except Exception as e:
                    logger.warning(f"Direct x.com capture failed: {e}")
                    browser.close()
                    raise

        except Exception as e:
            logger.warning(f"Failed to capture tweet screenshot: {e}")
            fallback = capture_screenshot_via_opencli(tweet_url, cache_path, full_page=False)
            if fallback:
                return fallback
            return None

    def capture_from_text(self, text: str) -> Path | None:
        """Extract tweet URL from text and capture screenshot.

        Args:
            text: Text containing Twitter/X URL

        Returns:
            Path to screenshot file, or None if no URL found or capture failed
        """
        url = self._extract_tweet_url(text)
        if not url:
            return None
        return self.capture(url)

    def capture_multiple(self, urls: list[str]) -> dict[str, Path]:
        """Capture screenshots for multiple tweets.

        Args:
            urls: List of Twitter/X URLs

        Returns:
            Dict mapping URLs to screenshot paths (None if failed)
        """
        results = {}
        for url in urls:
            results[url] = self.capture(url)
        return results
