from __future__ import annotations

import json
import os
import shlex
import select
import subprocess
import time
import base64
import mimetypes
from pathlib import Path
from dataclasses import dataclass
from loguru import logger


@dataclass
class MiniMaxSearchResult:
    title: str = ""
    url: str = ""
    snippet: str = ""
    date: str = ""

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "date": self.date,
        }


class MiniMaxMCPClient:
    """Minimal stdio MCP client for MiniMax coding-plan search tools."""

    def __init__(
        self,
        api_key: str | None = None,
        api_host: str | None = None,
        command: str | list[str] | None = None,
        timeout: float = 10.0,
    ):
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self.api_host = api_host or os.environ.get("MINIMAX_API_HOST", "https://api.minimaxi.com")
        # Use direct python module instead of uvx to avoid startup overhead
        self.command = command or os.environ.get("MINIMAX_MCP_COMMAND", "python -m minimax_mcp.server")
        self.timeout = timeout

    def web_search(self, query: str, max_results: int = 5) -> list[dict]:
        if not query.strip() or not self.api_key:
            return []

        try:
            payload = self._call_tool("web_search", {"query": query})
            results = self._extract_results(payload)
            if not results:
                return []
            deduped: list[dict] = []
            seen_urls: set[str] = set()
            for result in results:
                url = (result.get("url") or "").strip()
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                deduped.append(result)
                if len(deduped) >= max_results:
                    break
            return deduped
        except Exception as e:
            logger.debug(f"MiniMax MCP web_search failed: {e}")
            return []

    def understand_image(self, prompt: str, image_url: str) -> str:
        if not prompt.strip() or not image_url.strip() or not self.api_key:
            return ""

        direct_text = self._understand_image_direct(prompt, image_url)
        if direct_text:
            return direct_text

        try:
            payload = self._call_tool(
                "understand_image",
                {"prompt": prompt, "image_url": image_url},
            )
            text = self._extract_text(payload)
            return text.strip()
        except Exception as e:
            logger.debug(f"MiniMax MCP understand_image failed: {e}")
            return ""

    def _understand_image_direct(self, prompt: str, image_url: str) -> str:
        try:
            import requests

            processed_image = self._prepare_image_source(image_url)
            payload = {
                "prompt": prompt,
                "image_url": processed_image,
            }
            response = requests.post(
                f"{self.api_host.rstrip('/')}/v1/coding_plan/vlm",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "MM-API-Source": "gongzhonghao-direct",
                    "Content-Type": "application/json",
                },
                timeout=float(os.environ.get("MINIMAX_VLM_TIMEOUT_SECONDS", self.timeout or 30)),
            )
            response.raise_for_status()
            data = response.json()
            base_resp = data.get("base_resp", {}) if isinstance(data, dict) else {}
            if base_resp and base_resp.get("status_code") not in (0, None):
                raise RuntimeError(f"{base_resp.get('status_code')}-{base_resp.get('status_msg')}")
            content = data.get("content", "") if isinstance(data, dict) else ""
            return content.strip() if isinstance(content, str) else ""
        except Exception as e:
            logger.debug(f"MiniMax direct understand_image failed: {e}")
            return ""

    @staticmethod
    def _prepare_image_source(image_url: str) -> str:
        image_url = image_url.strip()
        if image_url.startswith("data:"):
            return image_url

        if image_url.startswith(("http://", "https://")):
            # Multi-modal models often fail to fetch remote URLs directly from certain regions.
            # Downloading locally and sending as base64 is more robust.
            try:
                import requests
                # Use a larger timeout as some sources might be slow
                resp = requests.get(
                    image_url,
                    timeout=20,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    },
                )
                resp.raise_for_status()
                content = resp.content

                # Check for reasonable size (e.g., 8MB) - MiniMax usually has limits
                if len(content) > 8 * 1024 * 1024:
                    logger.debug(f"Image {image_url} is too large ({len(content)} bytes), sending URL instead.")
                    return image_url

                mime_type = resp.headers.get("Content-Type", "").split(";")[0]
                if not mime_type or "image" not in mime_type:
                    mime_type = mimetypes.guess_type(image_url)[0] or "image/jpeg"

                encoded = base64.b64encode(content).decode("ascii")
                return f"data:{mime_type};base64,{encoded}"
            except Exception as e:
                logger.debug(f"Failed to pre-download image from {image_url}: {e}")
                return image_url

        # Handle local file paths
        path = Path(image_url[1:] if image_url.startswith("@") else image_url)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {path}")
        
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        if mime_type not in {"image/jpeg", "image/png", "image/webp"} and "gif" in mime_type:
            mime_type = "image/gif"
        
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _call_tool(self, tool_name: str, arguments: dict) -> dict | list | str:
        command = self._resolve_command()
        if not command:
            raise RuntimeError("MiniMax MCP command is not configured")

        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = self.api_key
        env["MINIMAX_API_HOST"] = self.api_host

        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        try:
            self._send_message(proc, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "gongzhonghao",
                        "version": "1.0",
                    },
                },
            })
            self._read_until_id(proc, 1)
            self._send_message(proc, {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            })
            self._send_message(proc, {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            })
            response = self._read_until_id(proc, 2)
            if "error" in response:
                raise RuntimeError(response["error"])
            return response.get("result", {})
        finally:
            self._terminate(proc)

    def _resolve_command(self) -> list[str]:
        if isinstance(self.command, list):
            return self.command
        if isinstance(self.command, str) and self.command.strip():
            return shlex.split(self.command)
        return []

    def _send_message(self, proc: subprocess.Popen, message: dict) -> None:
        if not proc.stdin:
            raise RuntimeError("MiniMax MCP stdin unavailable")
        data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
        proc.stdin.write(header + data)
        proc.stdin.flush()

    def _read_message(self, proc: subprocess.Popen) -> dict:
        if not proc.stdout:
            raise RuntimeError("MiniMax MCP stdout unavailable")
        headers = {}
        start = time.time()
        while True:
            if self.timeout and (time.time() - start) > self.timeout:
                raise TimeoutError("Timed out waiting for MCP response headers")
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("MiniMax MCP process closed unexpectedly")
            line = line.decode("utf-8", errors="ignore").strip()
            if not line:
                break
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        if length <= 0:
            raise RuntimeError("Invalid MCP response length")
        body = proc.stdout.read(length)
        if not body:
            raise RuntimeError("Empty MCP response body")
        return json.loads(body.decode("utf-8", errors="ignore"))

    def _read_until_id(self, proc: subprocess.Popen, msg_id: int) -> dict:
        deadline = time.time() + self.timeout if self.timeout else None
        while True:
            if deadline and time.time() > deadline:
                raise TimeoutError(f"Timed out waiting for MCP message {msg_id}")
            if proc.stdout and select.select([proc.stdout], [], [], 0.2)[0]:
                msg = self._read_message(proc)
                if msg.get("id") == msg_id:
                    return msg
            elif proc.poll() is not None:
                stderr = ""
                if proc.stderr:
                    try:
                        stderr = proc.stderr.read().decode("utf-8", errors="ignore")
                    except Exception:
                        stderr = ""
                raise RuntimeError(f"MCP process exited early: {stderr[:500]}")

    @staticmethod
    def _extract_results(payload: dict | list | str) -> list[dict]:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return []

        if isinstance(payload, list):
            items = []
            for item in payload:
                items.extend(MiniMaxMCPClient._extract_results(item))
            return items

        if not isinstance(payload, dict):
            return []

        if "content" in payload and isinstance(payload["content"], list):
            text_blobs = []
            for block in payload["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_blobs.append(block.get("text", ""))
            if text_blobs:
                joined = "\n".join(text_blobs)
                return MiniMaxMCPClient._extract_results(joined)

        for key in ("results", "organic", "items", "search_results", "data"):
            value = payload.get(key)
            if isinstance(value, list) and value:
                parsed = []
                for item in value:
                    if isinstance(item, dict):
                        parsed.append({
                            "title": item.get("title", item.get("name", "")),
                            "url": item.get("url", item.get("link", "")),
                            "snippet": item.get("snippet", item.get("description", item.get("content", ""))),
                            "date": item.get("date", item.get("published", "")),
                        })
                if parsed:
                    return parsed

        text = payload.get("text") or payload.get("output") or ""
        if isinstance(text, str) and text.strip():
            try:
                parsed = json.loads(text)
                return MiniMaxMCPClient._extract_results(parsed)
            except Exception:
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                results = []
                current = {}
                for line in lines:
                    if line.startswith(("http://", "https://")):
                        current["url"] = line
                    elif line.startswith("- ") or line.startswith("* "):
                        current.setdefault("snippet", line[2:].strip())
                    elif not current.get("title"):
                        current["title"] = line
                    else:
                        current.setdefault("snippet", line)
                    if current.get("title") and current.get("url"):
                        results.append(current)
                        current = {}
                return results

        return []

    @staticmethod
    def _extract_text(payload: dict | list | str) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, list):
            parts = [MiniMaxMCPClient._extract_text(item) for item in payload]
            return "\n".join(part for part in parts if part)
        if not isinstance(payload, dict):
            return ""

        if "content" in payload and isinstance(payload["content"], list):
            text_blobs = []
            for block in payload["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_blobs.append(block.get("text", ""))
            if text_blobs:
                return "\n".join(text_blobs)

        for key in ("text", "output", "result", "message"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                text = MiniMaxMCPClient._extract_text(value)
                if text:
                    return text

        return ""

    def _terminate(self, proc: subprocess.Popen) -> None:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
        except Exception:
            pass
