"""Helpers for invoking OpenCLI search commands."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from loguru import logger


_DEFAULT_WEB_SEARCH_PROVIDERS = ("google", "duckduckgo", "brave", "yahoo")


def _run_opencli_search(args: list[str], timeout: int = 180) -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            ["opencli", *args, "-f", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        logger.debug("opencli binary not found, skipping OpenCLI search")
        return []
    except Exception as e:
        logger.debug(f"OpenCLI search failed to start: {e}")
        return []

    output = (proc.stdout or proc.stderr or "").strip()
    if not output:
        return []
    if _looks_like_search_blocked(output):
        logger.debug(f"OpenCLI search blocked by challenge: {' '.join(args[:2])}")
        return []

    try:
        data = json.loads(output)
    except json.JSONDecodeError as e:
        logger.debug(f"OpenCLI search returned non-JSON output: {e}")
        return []

    if isinstance(data, dict):
        if "results" in data and isinstance(data["results"], list):
            data = data["results"]
        elif "items" in data and isinstance(data["items"], list):
            data = data["items"]
        else:
            data = [data]

    if not isinstance(data, list):
        return []

    results: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            results.append(item)
    return results


def _looks_like_search_blocked(output: str) -> bool:
    lowered = output.lower()
    blocked_markers = (
        "captcha",
        "unusual traffic",
        "verify you are human",
        "human verification",
        "人机验证",
        "验证您是真人",
        "检测到异常流量",
    )
    return any(marker in lowered for marker in blocked_markers)


def _web_search_providers() -> list[str]:
    raw = os.environ.get("OPENCLI_WEB_SEARCH_PROVIDERS", "")
    providers = [p.strip().lower() for p in raw.split(",") if p.strip()] if raw else list(_DEFAULT_WEB_SEARCH_PROVIDERS)
    seen = set()
    ordered = []
    for provider in providers:
        if provider == "bing":
            provider = "yahoo"  # OpenCLI has no bing adapter; Yahoo is Bing-powered.
        if provider == "quark":
            logger.debug("Skipping OpenCLI quark provider: adapter is Quark Drive, not web search")
            continue
        if provider not in seen:
            seen.add(provider)
            ordered.append(provider)
    return ordered


def provider_search(provider: str, query: str, limit: int = 5, timeout: int = 180) -> list[dict[str, Any]]:
    provider = (provider or "").strip().lower()
    if provider == "bing":
        provider = "yahoo"
    if provider == "quark":
        return []
    return _run_opencli_search([provider, "search", query, "--limit", str(limit)], timeout=timeout)


def web_search(query: str, limit: int = 5, timeout: int = 180) -> list[dict[str, Any]]:
    """Search the web with provider fallback.

    Google is tried first for quality, but browser captcha/human verification
    failures should not block the pipeline; fallback providers are controlled by
    OPENCLI_WEB_SEARCH_PROVIDERS (default: google,duckduckgo,brave,yahoo).
    """
    for provider in _web_search_providers():
        results = provider_search(provider, query, limit=limit, timeout=timeout)
        if results:
            if provider != "google":
                logger.info(f"OpenCLI web search used fallback provider: {provider}")
            return results
    return []


def google_search(query: str, limit: int = 5, timeout: int = 180) -> list[dict[str, Any]]:
    return web_search(query, limit=limit, timeout=timeout)


def twitter_search(query: str, limit: int = 5, timeout: int = 180) -> list[dict[str, Any]]:
    return _run_opencli_search(["twitter", "search", query, "--limit", str(limit)], timeout=timeout)


def reddit_search(
    query: str,
    limit: int = 5,
    timeout: int = 180,
    time_filter: str | None = None,
    sort: str | None = None,
) -> list[dict[str, Any]]:
    args = ["reddit", "search", query, "--limit", str(limit)]
    if time_filter:
        args.extend(["--time", str(time_filter)])
    if sort:
        args.extend(["--sort", str(sort)])
    return _run_opencli_search(args, timeout=timeout)
