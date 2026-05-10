# src/image/generator.py
"""Image generator using MiniMax API."""

import os
import re
import time
from pathlib import Path

import requests
from loguru import logger


class ImageGenerator:
    """Generate images via MiniMax image-01 API."""

    API_URL = "https://api.minimax.chat/v1/image_generation"
    DEFAULT_MODEL = "image-01"

    def __init__(self):
        self.enabled = True
        self.api_key = os.environ.get("MINIMAX_API_KEY") or os.environ.get("IMAGE_API_KEY")
        self.model = self.DEFAULT_MODEL

    def _call_api(self, prompt: str, aspect_ratio: str = "16:9", n: int = 1) -> dict:
        """Call MiniMax image generation API."""
        if not self.api_key:
            raise RuntimeError("MiniMax API key not configured. Set MINIMAX_API_KEY or IMAGE_API_KEY env var.")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
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
        """Download image from URL to local path."""
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
        """Generate an image from text prompt via MiniMax.

        Args:
            prompt: Text description for image generation
            size: Image size, e.g. "1024x576", "1024x1024". Maps to aspect_ratio.
            quality: Image quality - "low", "medium", "high" (unused, MiniMax has fixed quality)
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

        # Call API
        data = self._call_api(prompt, aspect_ratio=aspect_ratio, n=1)

        # Extract image URL from response
        # Response format: {"data": {"image_urls": ["url1", ...]}, "base_resp": {...}}
        image_urls = data.get("data", {}).get("image_urls", [])
        if not image_urls:
            raise RuntimeError(f"MiniMax returned no image URLs. Response: {data}")

        image_url = image_urls[0]

        if output_path is None:
            output_path = "output/cover/generated.png"

        return self._download_image(image_url, output_path)

    def generate_cover(self, article_title: str, article_summary: str = "") -> Path:
        """Generate a cover image for an AI news article."""
        prompt = (
            "A futuristic AI technology news cover image for a WeChat official account. "
            "Digital art style, vibrant colors, professional magazine cover design. "
            "Elements: neural network visualization, holographic displays, "
            "data streams, abstract geometric patterns, glowing circuits. "
            "Modern, high quality, no text overlay."
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
