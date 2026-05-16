# src/image/generator.py
"""Image generation through OpenCLI browser-backed image adapters."""

import os
import base64
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests
from loguru import logger


class ImageGenerator:
    """Generate images via the configured image provider."""

    API_URL = "https://api.minimax.chat/v1/image_generation"
    DEFAULT_MODEL = "image-01"

    def __init__(self):
        self.enabled = True
        self.provider = os.environ.get("IMAGE_PROVIDER", "gemini").strip().lower()
        fallback_env = os.environ.get("IMAGE_FALLBACK_PROVIDERS", "chatgpt")
        self.fallback_providers = [p.strip().lower() for p in fallback_env.split(",") if p.strip()]
        self.opencli_timeout = int(os.environ.get("OPENCLI_IMAGE_TIMEOUT", "360"))
        self.minimax_api_key = os.environ.get("MINIMAX_API_KEY") or os.environ.get("IMAGE_API_KEY")
        self.model = self.DEFAULT_MODEL

        # Validate provider and credentials
        if self.provider == "minimax" and not self.minimax_api_key:
            logger.warning("MiniMax image provider requested but MINIMAX_API_KEY is missing; falling back to gemini")
            self.provider = "gemini"

    def _call_api_for_provider(self, provider: str, prompt: str, aspect_ratio: str = "16:9", n: int = 1) -> dict:
        """Call the configured image generation API."""
        if provider in {"gemini", "chatgpt"}:
            return self._call_opencli_image(provider, prompt, aspect_ratio=aspect_ratio)
        return self._call_minimax_api(prompt, aspect_ratio=aspect_ratio, n=n)

    def _call_opencli_image(self, provider: str, prompt: str, aspect_ratio: str = "16:9") -> dict:
        """Call an OpenCLI browser-backed image command and return the saved file."""
        output_dir = Path(os.environ.get("OPENCLI_IMAGE_OUTPUT_DIR", "output/generated_images"))
        output_dir.mkdir(parents=True, exist_ok=True)

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
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.opencli_timeout + 30,
            check=False,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            raise RuntimeError(f"opencli {provider} image failed ({proc.returncode}): {stderr or stdout}")

        file_path = self._extract_opencli_image_file(proc.stdout)
        if not file_path:
            raise RuntimeError(f"opencli {provider} image returned no file. Output: {proc.stdout[:500]}")

        return {
            "provider": provider,
            "file": file_path,
            "raw": proc.stdout,
        }

    @staticmethod
    def _extract_opencli_image_file(output: str) -> str:
        output = (output or "").strip()
        if not output:
            return ""

        try:
            data = json.loads(output)
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if isinstance(item, dict):
                    value = item.get("file") or item.get("path")
                    if value:
                        return str(value)
        except json.JSONDecodeError:
            pass

        match = re.search(r'(?:"file"\s*:\s*"([^"]+)")', output)
        if match:
            return match.group(1)

        for token in re.findall(r'(/[^\s"\']+\.(?:png|jpg|jpeg|webp))', output, flags=re.I):
            return token
        for token in re.findall(r'([A-Za-z0-9_./-]+\.(?:png|jpg|jpeg|webp))', output, flags=re.I):
            return token
        return ""

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

        providers = [self.provider] + [p for p in self.fallback_providers if p != self.provider]

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

        if self.provider in {"gemini", "chatgpt"}:
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

    def generate_cover(self, article_title: str, article_summary: str = "") -> Path:
        """Generate a cover image for an AI news article."""
        prompt = (
            "A futuristic AI technology news cover image for a WeChat official account, "
            "generated by Google Nano Banana 2. "
            "Digital art style, vibrant colors, professional magazine cover design. "
            "Elements: neural network visualization, holographic displays, "
            "data streams, abstract geometric patterns, glowing circuits. "
            "Modern, high quality, no text overlay, extremely clean composition."
        )
        if article_title:
            prompt += f" Theme: {article_title}."
        if article_summary:
            prompt += f" Context: {article_summary[:100]}."

        return self.generate(prompt, size="1024x576", quality="medium")

    def generate_illustration(
        self,
        topic: str,
        context: str = "",
        output_path: str = None,
        article_title: str = "",
        source_name: str = "",
    ) -> Path:
        """Generate an illustration for a specific article section."""
        prompt = (
            f"An illustration about {topic} in AI/technology context. "
            "Digital art style, clean design, suitable for a news article. "
            "Abstract tech visualization, modern graphics, professional quality, "
            "vibrant but not overwhelming colors. No text overlay. "
            "Avoid unrelated company logos, product screenshots, and brand-specific UI."
        )
        if article_title:
            prompt += f" Article theme: {article_title}."
        if source_name:
            prompt += f" Source: {source_name}."
        if context:
            prompt += f" Additional context: {context[:100]}."

        return self.generate(prompt, size="800x448", quality="low", output_path=output_path)
