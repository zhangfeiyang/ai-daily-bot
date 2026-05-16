"""Helpers for invoking OpenCLI search commands."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from loguru import logger


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


def google_search(query: str, limit: int = 5, timeout: int = 180) -> list[dict[str, Any]]:
    return _run_opencli_search(["google", "search", query, "--limit", str(limit)], timeout=timeout)


def twitter_search(query: str, limit: int = 5, timeout: int = 180) -> list[dict[str, Any]]:
    return _run_opencli_search(["twitter", "search", query, "--limit", str(limit)], timeout=timeout)


def reddit_search(query: str, limit: int = 5, timeout: int = 180) -> list[dict[str, Any]]:
    return _run_opencli_search(["reddit", "search", query, "--limit", str(limit)], timeout=timeout)
