# src/utils/huggingface_screenshot.py
"""Capture HuggingFace page screenshots using Playwright."""

import hashlib
import re
from pathlib import Path

from loguru import logger


class HuggingFaceScreenshot:
    """Capture screenshots of HuggingFace model/dataset/space pages."""

    def __init__(self):
        self.output_dir = Path("output/huggingface_screenshots")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, url: str) -> Path:
        """Get cache file path for a URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        return self.output_dir / f"hf_{url_hash}.png"

    def capture(self, page_url: str) -> Path | None:
        """Capture a screenshot of a HuggingFace page.

        Args:
            page_url: HuggingFace model/dataset/space URL

        Returns:
            Path to screenshot file, or None if failed
        """
        cache_path = self._get_cache_path(page_url)
        if cache_path.exists():
            logger.debug(f"Using cached HuggingFace screenshot: {cache_path}")
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
                    return None

                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )

                page = context.new_page()
                logger.info(f"Capturing HuggingFace screenshot: {page_url}")

                try:
                    response = page.goto(page_url, wait_until="networkidle", timeout=30000)
                    if response and response.status < 400:
                        page.wait_for_timeout(3000)

                        # Try to find main content area
                        selectors = [
                            "main",
                            "[class*='model-card']",
                            "[class*='ModelCard']",
                            ".prose",
                            "article",
                        ]
                        for selector in selectors:
                            try:
                                element = page.query_selector(selector)
                                if element:
                                    element.screenshot(path=str(cache_path))
                                    browser.close()
                                    logger.info(f"HuggingFace screenshot saved: {cache_path}")
                                    return cache_path
                            except:
                                continue

                        # Fallback: screenshot viewport
                        page.screenshot(path=str(cache_path), full_page=False)
                        browser.close()
                        return cache_path
                except Exception as e:
                    logger.warning(f"HuggingFace capture failed: {e}")
                    browser.close()
                    return None

        except Exception as e:
            logger.warning(f"Failed to capture HuggingFace screenshot: {e}")
            return None
