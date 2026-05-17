# src/image/generator.py
"""Image generation through OpenCLI browser-backed image adapters."""

import os
import base64
import json
import re
import shutil
import subprocess
import time
import random
import threading
from pathlib import Path

import requests
from loguru import logger


class ImageGenerator:
    """Generate images via the configured image provider."""

    API_URL = "https://api.minimax.chat/v1/image_generation"
    DEFAULT_MODEL = "image-01"
    _rotation_lock = threading.Lock()

    def __init__(self):
        self.enabled = True
        self.provider = os.environ.get("IMAGE_PROVIDER", "gemini").strip().lower()
        fallback_env = os.environ.get("IMAGE_FALLBACK_PROVIDERS", "doubao,chatgpt")
        self.fallback_providers = [p.strip().lower() for p in fallback_env.split(",") if p.strip()]
        self.primary_provider_strategy = os.environ.get("IMAGE_PRIMARY_PROVIDER_STRATEGY", "rotate").strip().lower()
        self.rotation_state_path = Path(
            os.environ.get("IMAGE_PROVIDER_ROTATION_STATE", "output/cache/image_provider_rotation.json")
        )
        self.opencli_timeout = int(os.environ.get("OPENCLI_IMAGE_TIMEOUT", "180"))
        self.opencli_grace_period = int(os.environ.get("OPENCLI_IMAGE_GRACE_PERIOD", "180"))
        self.opencli_poll_interval = int(os.environ.get("OPENCLI_IMAGE_POLL_INTERVAL", "10"))
        self.opencli_prompt_body_limit = int(os.environ.get("OPENCLI_IMAGE_PROMPT_BODY_LIMIT", "6000"))
        self.minimax_api_key = os.environ.get("MINIMAX_API_KEY") or os.environ.get("IMAGE_API_KEY")
        self.model = self.DEFAULT_MODEL

        # Validate provider and credentials
        if self.provider == "minimax" and not self.minimax_api_key:
            logger.warning("MiniMax image provider requested but MINIMAX_API_KEY is missing; falling back to gemini")
            self.provider = "gemini"

    def _call_api_for_provider(self, provider: str, prompt: str, aspect_ratio: str = "16:9", n: int = 1) -> dict:
        """Call the configured image generation API."""
        if provider in {"gemini", "doubao", "chatgpt"}:
            return self._call_opencli_image(provider, prompt, aspect_ratio=aspect_ratio)
        return self._call_minimax_api(prompt, aspect_ratio=aspect_ratio, n=n)

    def _call_opencli_image(self, provider: str, prompt: str, aspect_ratio: str = "16:9") -> dict:
        """Call an OpenCLI browser-backed image command and return the saved file."""
        output_dir = Path(os.environ.get("OPENCLI_IMAGE_OUTPUT_DIR", "output/generated_images"))
        output_dir.mkdir(parents=True, exist_ok=True)
        existing_files = {p.resolve() for p in output_dir.glob("**/*") if p.is_file()}

        cmd = [
            "opencli",
            provider,
            "image",
            prompt,
            "--op",
            str(output_dir),
            "--timeout",
            str(self.opencli_timeout),
            "-f",
            "json",
        ]
        if provider == "gemini":
            cmd.extend(["--rt", aspect_ratio])

        logger.info(f"Calling OpenCLI image provider '{provider}': prompt={prompt[:60]}...")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise RuntimeError(f"opencli {provider} image failed to start: {exc}") from exc

        deadline = time.time() + self.opencli_timeout
        raw_stdout = ""
        raw_stderr = ""
        while True:
            generated_file = self._find_opencli_image_file(output_dir, existing_files)
            if generated_file:
                raw_stdout, raw_stderr = self._stop_opencli_process(proc)
                return {
                    "provider": provider,
                    "file": str(generated_file),
                    "raw": raw_stdout or raw_stderr or "opencli image completed",
                }

            if proc.poll() is not None:
                raw_stdout, raw_stderr = proc.communicate()
                output = (raw_stderr or "").strip() or (raw_stdout or "").strip()
                if proc.returncode != 0:
                    if self._opencli_error_may_finish_late(output):
                        generated_file = self._wait_for_opencli_image_file(output_dir, existing_files)
                        if generated_file:
                            return {
                                "provider": provider,
                                "file": str(generated_file),
                                "raw": raw_stdout,
                            }
                    raise RuntimeError(f"opencli {provider} image failed ({proc.returncode}): {output}")

                file_path = self._extract_opencli_image_file(raw_stdout)
                if not file_path or self._is_opencli_file_placeholder(file_path):
                    generated_file = self._wait_for_opencli_image_file(output_dir, existing_files)
                    if not generated_file:
                        raise RuntimeError(f"opencli {provider} image returned no file. Output: {raw_stdout[:500]}")
                else:
                    generated_file = Path(file_path).expanduser()
                    if not generated_file.exists():
                        generated_file = self._wait_for_opencli_image_file(output_dir, existing_files)
                    if not generated_file:
                        raise RuntimeError(f"opencli {provider} image returned missing file: {file_path}")

                return {
                    "provider": provider,
                    "file": str(generated_file),
                    "raw": raw_stdout,
                }

            if time.time() >= deadline:
                raw_stdout, raw_stderr = self._stop_opencli_process(proc)
                generated_file = self._wait_for_opencli_image_file(output_dir, existing_files)
                if generated_file:
                    return {
                        "provider": provider,
                        "file": str(generated_file),
                        "raw": raw_stdout or f"opencli timed out after {self.opencli_timeout}s",
                    }
                raise RuntimeError(f"opencli {provider} image timed out after {self.opencli_timeout}s")

            time.sleep(self.opencli_poll_interval)

    def _wait_for_opencli_image_file(self, output_dir: Path, existing_files: set[Path]) -> Path | None:
        """Poll the output directory for a newly written OpenCLI image file."""
        deadline = time.time() + self.opencli_grace_period
        while time.time() < deadline:
            candidate = self._find_opencli_image_file(output_dir, existing_files)
            if candidate:
                logger.info(f"OpenCLI image appeared after wait: {candidate}")
                return candidate

            time.sleep(self.opencli_poll_interval)
        return None

    def _find_opencli_image_file(self, output_dir: Path, existing_files: set[Path]) -> Path | None:
        image_exts = (".png", ".jpg", ".jpeg", ".webp")
        candidates = []
        for path in output_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in image_exts:
                continue
            try:
                resolved = path.resolve()
            except Exception:
                continue
            if resolved in existing_files:
                continue
            try:
                if path.stat().st_mtime < time.time() - self.opencli_grace_period:
                    continue
            except OSError:
                continue
            candidates.append(path)
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]
        return None

    @staticmethod
    def _stop_opencli_process(proc: subprocess.Popen) -> tuple[str, str]:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    return proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    return proc.communicate()
        except Exception:
            pass
        try:
            return proc.communicate(timeout=1)
        except Exception:
            return "", ""

    @staticmethod
    def _normalize_opencli_file_value(value: str) -> str:
        cleaned = str(value or "").strip().strip('"').strip("'")
        cleaned = re.sub(r"^[^\w/~.\\\\.-]+", "", cleaned).strip()
        return cleaned

    @classmethod
    def _is_opencli_file_placeholder(cls, value: str) -> bool:
        cleaned = cls._normalize_opencli_file_value(value).lower()
        return cleaned in {"", "-", "none", "null", "n/a"}

    @classmethod
    def _extract_opencli_image_file(cls, output: str) -> str:
        output = (output or "").strip()
        if not output:
            return ""

        try:
            data = json.loads(output)
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if isinstance(item, dict):
                    value = cls._normalize_opencli_file_value(item.get("file") or item.get("path"))
                    if value and not cls._is_opencli_file_placeholder(value):
                        return value
        except json.JSONDecodeError:
            pass

        match = re.search(r'(?:"file"\s*:\s*"([^"]+)")', output)
        if match:
            value = cls._normalize_opencli_file_value(match.group(1))
            if not cls._is_opencli_file_placeholder(value):
                return value

        for token in re.findall(r'(/[^\s"\']+\.(?:png|jpg|jpeg|webp))', output, flags=re.I):
            return token
        for token in re.findall(r'([A-Za-z0-9_./-]+\.(?:png|jpg|jpeg|webp))', output, flags=re.I):
            return token
        return ""

    @staticmethod
    def _opencli_error_may_finish_late(output: str) -> bool:
        lowered = (output or "").lower()
        late_markers = (
            "empty_result",
            "no generated images",
            "returned no data",
            "no-images",
            "no images",
        )
        return any(marker in lowered for marker in late_markers)

    @staticmethod
    def _compact_text(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip()

    def _truncate_prompt_text(self, text: str, limit: int) -> str:
        compact = self._compact_text(text)
        if not compact or limit <= 0:
            return ""
        if len(compact) <= limit:
            return compact
        return compact[:limit].rstrip() + "..."

    def _build_opencli_prompt(
        self,
        intro: str,
        *,
        title_label: str = "",
        title: str = "",
        source_label: str = "",
        source: str = "",
        context_label: str = "",
        context: str = "",
        body_limit: int | None = None,
    ) -> str:
        parts = [self._compact_text(intro)]
        if title:
            parts.append(f"{title_label}: {self._truncate_prompt_text(title, 180)}")
        if source:
            parts.append(f"{source_label}: {self._truncate_prompt_text(source, 120)}")
        if context:
            limit = self.opencli_prompt_body_limit if body_limit is None else body_limit
            parts.append(f"{context_label}: {self._truncate_prompt_text(context, limit)}")
        return "\n\n".join(part for part in parts if part)

    def _call_minimax_api(self, prompt: str, aspect_ratio: str = "16:9", n: int = 1) -> dict:
        if not self.minimax_api_key:
            raise RuntimeError("MiniMax API key not configured. Set MINIMAX_API_KEY or IMAGE_API_KEY env var.")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.minimax_api_key}",
        }

        payload = {
            "model": self.model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "n": n,
        }

        logger.info(f"Calling MiniMax image API: prompt={prompt[:60]}...")
        t0 = time.time()

        resp = requests.post(self.API_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()

        data = resp.json()
        logger.info(f"MiniMax API responded in {time.time() - t0:.1f}s")
        return data

    def _download_image(self, image_url: str, output_path: str) -> Path:
        """Download image from URL to local path, supports Data URIs."""
        if image_url.startswith("data:"):
            header, encoded = image_url.split(",", 1)
            data = base64.b64decode(encoded)
            out_file = Path(output_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(data)
            logger.info(f"Image saved from Data URI to {out_file} ({len(data)} bytes)")
            return out_file

        resp = requests.get(image_url, timeout=60)
        resp.raise_for_status()

        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(resp.content)

        logger.info(f"Image downloaded to {out_file} ({len(resp.content)} bytes)")
        return out_file

    def _ordered_providers(self) -> list[str]:
        base: list[str] = []
        for provider in [self.provider, *self.fallback_providers, "gemini", "doubao", "chatgpt"]:
            provider = (provider or "").strip().lower()
            if provider and provider not in base:
                base.append(provider)

        primary_pair = [p for p in ("gemini", "doubao") if p in base]
        ordered: list[str]
        if len(primary_pair) == 2:
            if self.primary_provider_strategy == "random":
                first = random.choice(primary_pair)
            else:
                first = self._next_rotated_primary_provider(primary_pair)
            second = primary_pair[1] if primary_pair[0] == first else primary_pair[0]
            ordered = [first, second]
        else:
            ordered = primary_pair[:]

        for provider in base:
            if provider not in ordered:
                ordered.append(provider)
        return ordered

    def _next_rotated_primary_provider(self, primary_pair: list[str]) -> str:
        if not primary_pair:
            return self.provider
        default = primary_pair[0]
        try:
            with self._rotation_lock:
                self.rotation_state_path.parent.mkdir(parents=True, exist_ok=True)
                current = 0
                if self.rotation_state_path.exists():
                    try:
                        state = json.loads(self.rotation_state_path.read_text(encoding="utf-8"))
                        current = int(state.get("index", 0))
                    except Exception:
                        current = 0
                self.rotation_state_path.write_text(
                    json.dumps({"index": current + 1}, ensure_ascii=False),
                    encoding="utf-8",
                )
                return primary_pair[current % len(primary_pair)]
        except Exception as e:
            logger.debug(f"Primary provider rotation state unavailable: {e}")
            return default

    def generate(
        self,
        prompt: str,
        size: str = "1024x576",
        quality: str = "medium",
        output_path: str = None,
    ) -> Path:
        """Generate an image from text prompt via OpenCLI image adapters.

        Args:
            prompt: Text description for image generation
            size: Image size, e.g. "1024x576", "1024x1024". Maps to aspect_ratio.
            quality: Image quality - "low", "medium", "high" (reserved for providers that support it)
            output_path: Where to save the image

        Returns:
            Path to the generated image file
        """
        if not self.enabled:
            raise RuntimeError("Image generation is disabled by configuration")

        # Map size to aspect_ratio
        aspect_ratio_map = {
            "1024x1024": "1:1",
            "1024x576": "16:9",
            "576x1024": "9:16",
            "800x448": "16:9",
            "448x800": "9:16",
        }
        aspect_ratio = aspect_ratio_map.get(size, "16:9")

        providers = self._ordered_providers()

        data = None
        last_error = None
        for provider in providers:
            try:
                data = self._call_api_for_provider(provider, prompt, aspect_ratio=aspect_ratio, n=1)
                self.provider = provider
                break
            except Exception as e:
                last_error = e
                logger.warning(f"Image provider '{provider}' failed: {e}")
        if data is None:
            raise last_error or RuntimeError("No image provider available")

        if output_path is None:
            output_path = "output/cover/generated.png"

        if self.provider in {"gemini", "doubao", "chatgpt"}:
            generated_file = Path(data.get("file", "")).expanduser()
            if not generated_file.exists():
                raise RuntimeError(f"OpenCLI provider returned missing image file: {generated_file}")
            out_file = Path(output_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            if generated_file.resolve() != out_file.resolve():
                shutil.copy2(generated_file, out_file)
            logger.info(f"Image saved from OpenCLI {self.provider} to {out_file}")
            return out_file

        # MiniMax response format: {"data": {"image_urls": ["url1", ...]}, "base_resp": {...}}
        image_urls = data.get("data", {}).get("image_urls", [])
        if not image_urls:
            raise RuntimeError(f"MiniMax returned no image URLs. Response: {data}")
        return self._download_image(image_urls[0], output_path)

    def generate_cover(self, article_title: str, article_summary: str = "", output_path: str = None) -> Path:
        """Generate a cover image for an AI news article."""
        prompt = self._build_opencli_prompt(
            "为微信公众号 AI 新闻生成封面。风格按内容选择，不要默认数字艺术。",
            title_label="标题",
            title=article_title,
            context_label="正文与情境",
            context=article_summary,
            body_limit=self.opencli_prompt_body_limit,
        )
        return self.generate(prompt, size="1024x576", quality="medium", output_path=output_path)

    def generate_illustration(
        self,
        topic: str,
        context: str = "",
        output_path: str = None,
        article_title: str = "",
        source_name: str = "",
    ) -> Path:
        """Generate an illustration for a specific article section."""
        prompt = self._build_opencli_prompt(
            f"为 AI/科技新闻的这个小节生成配图，尽量贴合正文中的具体场景，不要默认数字艺术。",
            title_label="小节主题",
            title=topic,
            source_label="文章主题",
            source=article_title or source_name,
            context_label="正文与情境",
            context=context,
            body_limit=self.opencli_prompt_body_limit,
        )
        return self.generate(prompt, size="800x448", quality="low", output_path=output_path)
