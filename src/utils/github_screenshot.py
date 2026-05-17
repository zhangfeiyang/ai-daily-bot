# src/utils/github_screenshot.py
"""Capture GitHub repository and issue screenshots using Playwright."""

import hashlib
import re
from pathlib import Path

from loguru import logger

from src.utils.opencli_browser import capture_screenshot_via_opencli


class GitHubScreenshot:
    """Capture screenshots of GitHub repositories, issues, and PRs."""

    def __init__(self):
        self.output_dir = Path("output/github_screenshots")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _extract_github_url(self, text: str) -> str | None:
        """Extract GitHub URL from text."""
        patterns = [
            r'https?://(?:www\.)?github\.com/[^/\s]+/[^/\s]+(?:/issues/\d+)?(?:/pull/\d+)?(?:/releases)?(?:/blob/[^\s]+)?',
            r'https?://(?:www\.)?github\.com/[^/\s]+/[^/\s]+/?',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None

    def _get_cache_path(self, url: str) -> Path:
        """Get cache file path for a URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        return self.output_dir / f"github_{url_hash}.png"

    def capture(self, repo_url: str) -> Path | None:
        """Capture a screenshot of a GitHub page.

        Args:
            repo_url: GitHub repository, issue, or PR URL

        Returns:
            Path to screenshot file, or None if failed
        """
        cache_path = self._get_cache_path(repo_url)
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

                # Navigate to the GitHub page
                logger.info(f"Navigating to {repo_url}")
                page.goto(repo_url, wait_until="networkidle", timeout=30000)

                # Hide common overlays that might block content (like "N" or Sign in banners)
                try:
                    page.add_style_tag(content="""
                        .unauthenticated-signup-banner, 
                        .js-signin-signup-banner, 
                        .js-cookie-consent-banner,
                        #trial-signup-modal,
                        .Banner--privacy,
                        section[aria-label="Sign up banner"] {
                            display: none !important;
                        }
                    """)
                    # Also try to hide some potential "N" overlays or floating elements
                    page.evaluate("""
                        document.querySelectorAll('.js-sticky').forEach(el => el.style.position = 'static');
                        document.querySelectorAll('[class*="banner"], [class*="popup"], [class*="modal"]').forEach(el => {
                            if (el.innerText.length < 50) el.style.display = 'none'; 
                        });
                    """)
                except Exception:
                    pass

                # Wait for main content to load
                page.wait_for_selector("main, .repository-content, #repo-content-pjax-container", timeout=10000)

                # Scroll to capture more content
                page.evaluate("window.scrollTo(0, 300)")
                page.wait_for_timeout(500)

                # Take screenshot of the main content area
                # Try to find the main content element
                content_selectors = [
                    "main",
                    ".repository-content",
                    "[data-testid='repository-container-header']",
                    ".Layout-main",
                ]

                screenshot_path = str(cache_path)
                element_found = False

                for selector in content_selectors:
                    try:
                        element = page.locator(selector).first
                        if element.is_visible():
                            element.screenshot(path=screenshot_path)
                            element_found = True
                            logger.debug(f"Screenshot captured using selector: {selector}")
                            break
                    except Exception:
                        continue

                if not element_found:
                    # Fallback to full page screenshot
                    page.screenshot(path=screenshot_path, full_page=False)

                context.close()
                browser.close()

                if Path(screenshot_path).exists():
                    logger.info(f"GitHub screenshot saved: {screenshot_path}")
                    return Path(screenshot_path)

        except Exception as e:
            logger.warning(f"Failed to capture GitHub screenshot: {e}")

        fallback = capture_screenshot_via_opencli(repo_url, cache_path, full_page=False)
        if fallback:
            return fallback
        return None

    def capture_from_text(self, text: str) -> Path | None:
        """Extract GitHub URL from text and capture screenshot."""
        url = self._extract_github_url(text)
        if url:
            return self.capture(url)
        return None
