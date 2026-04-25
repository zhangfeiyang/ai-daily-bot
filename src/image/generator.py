# src/image/generator.py
"""Cloud image generator using gpt-image-2 API for cover and article illustrations."""

import base64
import time
from pathlib import Path

import requests
from loguru import logger

from src.config import load_config


class ImageGenerator:
    """Generate images via gpt-image-2 API."""

    def __init__(self):
        llm_config = load_config("llm")
        cfg = llm_config.get("providers", {}).get("image", {})
        self.api_key = cfg.get("api_key", "")
        self.base_url = cfg.get("base_url", "").rstrip("/")
        self.model = cfg.get("model", "gpt-image-2")

    def generate(
        self,
        prompt: str,
        size: str = "1024x576",
        quality: str = "medium",
        output_path: str = None,
    ) -> Path:
        """Generate an image from text prompt via API.

        Args:
            prompt: Text description for image generation
            size: Image size, e.g. "1024x576", "1024x1024"
            quality: Image quality - "low", "medium", "high"
            output_path: Where to save the image

        Returns:
            Path to the generated image file
        """
        logger.info(f"Generating image via {self.model}: {prompt[:60]}...")
        t0 = time.time()

        url = f"{self.base_url}/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "quality": quality,
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        # Parse response - may return base64 or url
        img_data = data.get("data", [{}])[0]

        if "b64_json" in img_data:
            img_bytes = base64.b64decode(img_data["b64_json"])
        elif "url" in img_data:
            img_url = img_data["url"]
            img_resp = requests.get(img_url, timeout=60)
            img_resp.raise_for_status()
            img_bytes = img_resp.content
        else:
            raise ValueError(f"No image data in response: {list(img_data.keys())}")

        if output_path is None:
            output_path = "output/cover/generated.png"

        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(img_bytes)

        logger.info(f"Image generated in {time.time() - t0:.1f}s, saved to {out_file}")
        return out_file

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

    def generate_illustration(self, topic: str, context: str = "", output_path: str = None) -> Path:
        """Generate an illustration for a specific article section."""
        prompt = (
            f"An illustration about {topic} in AI/technology context. "
            "Digital art style, clean design, suitable for news article. "
            "Abstract tech visualization, modern graphics, professional quality, "
            "vibrant but not overwhelming colors. No text overlay."
        )
        if context:
            prompt += f" Additional context: {context[:100]}."

        return self.generate(prompt, size="800x448", quality="low", output_path=output_path)
