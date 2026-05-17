"""Helpers for using OpenCLI browser sessions as a fallback backend."""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from loguru import logger


def _run_opencli_browser(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["opencli", "browser", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        logger.debug("opencli binary not found, skipping OpenCLI browser fallback")
    except Exception as e:
        logger.debug(f"OpenCLI browser command failed to start: {e}")
    return None


def _parse_opencli_json(output: str) -> dict:
    try:
        data = json.loads((output or "").strip())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def capture_screenshot_via_opencli(
    url: str,
    output_path: str | Path,
    *,
    full_page: bool = False,
    timeout: int = 180,
    window: str = "background",
) -> Path | None:
    """Capture a screenshot using an OpenCLI browser session."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    session = f"codexshot-{uuid.uuid4().hex[:8]}"
    tab_id = ""
    try:
        open_args = [session, "open", url]
        if window:
            open_args.extend(["--window", window])
        proc = _run_opencli_browser(open_args, timeout=timeout)
        if not proc or proc.returncode != 0:
            if proc and window:
                proc = _run_opencli_browser([session, "open", url], timeout=timeout)
            if not proc or proc.returncode != 0:
                stderr = (proc.stderr or "").strip() if proc else ""
                stdout = (proc.stdout or "").strip() if proc else ""
                raise RuntimeError(f"opencli browser open failed: {stderr or stdout}")

        opened = _parse_opencli_json(proc.stdout)
        tab_id = str(opened.get("page") or opened.get("tab") or opened.get("target") or "").strip()
        if not tab_id:
            raise RuntimeError(f"opencli browser open returned no tab id: {proc.stdout}")

        shot_args = [session, "screenshot", str(output_path), "--tab", tab_id]
        if full_page:
            shot_args.append("--full-page")
        proc = _run_opencli_browser(shot_args, timeout=timeout)
        if not proc or proc.returncode != 0:
            stderr = (proc.stderr or "").strip() if proc else ""
            stdout = (proc.stdout or "").strip() if proc else ""
            raise RuntimeError(f"opencli browser screenshot failed: {stderr or stdout}")

        if output_path.exists():
            logger.info(f"OpenCLI browser screenshot saved: {output_path}")
            return output_path
        return None
    except Exception as e:
        logger.debug(f"OpenCLI browser screenshot fallback failed for {url}: {e}")
        return None
    finally:
        # Best effort cleanup; the browser bridge keeps the actual Chrome profile alive.
        if tab_id:
            _run_opencli_browser([session, "tab", "close", tab_id], timeout=30)
        _run_opencli_browser([session, "close"], timeout=30)


def fetch_html_via_opencli(
    url: str,
    *,
    timeout: int = 180,
    max_chars: int = 0,
) -> str | None:
    """Fetch rendered HTML using an OpenCLI browser session."""
    session = f"codexfetch-{uuid.uuid4().hex[:8]}"
    tab_id = ""
    try:
        proc = _run_opencli_browser([session, "open", url, "--window", "background"], timeout=timeout)
        if not proc or proc.returncode != 0:
            proc = _run_opencli_browser([session, "open", url], timeout=timeout)
        if not proc or proc.returncode != 0:
            stderr = (proc.stderr or "").strip() if proc else ""
            stdout = (proc.stdout or "").strip() if proc else ""
            raise RuntimeError(f"opencli browser open failed: {stderr or stdout}")

        opened = _parse_opencli_json(proc.stdout)
        tab_id = str(opened.get("page") or opened.get("tab") or opened.get("target") or "").strip()
        if not tab_id:
            raise RuntimeError(f"opencli browser open returned no tab id: {proc.stdout}")

        html_args = [session, "get", "html", "--tab", tab_id]
        if max_chars >= 0:
            html_args.extend(["--max", str(max_chars)])
        proc = _run_opencli_browser(html_args, timeout=timeout)
        if not proc or proc.returncode != 0:
            stderr = (proc.stderr or "").strip() if proc else ""
            stdout = (proc.stdout or "").strip() if proc else ""
            raise RuntimeError(f"opencli browser get html failed: {stderr or stdout}")

        output = (proc.stdout or "").strip()
        if not output:
            return None
        if output.startswith("<!-- opencli: truncated"):
            lines = output.splitlines()
            output = "\n".join(lines[1:]).strip()
        return output or None
    except Exception as e:
        logger.debug(f"OpenCLI browser HTML fetch failed for {url}: {e}")
        return None
    finally:
        if tab_id:
            _run_opencli_browser([session, "tab", "close", tab_id], timeout=30)
        _run_opencli_browser([session, "close"], timeout=30)
