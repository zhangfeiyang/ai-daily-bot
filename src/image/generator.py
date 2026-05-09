# src/image/generator.py
"""Image generator using Codex gpt-5.5 built-in image_gen tool."""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from loguru import logger


class ImageGenerator:
    """Generate images via Codex gpt-5.5 with built-in image_gen skill."""

    def __init__(self):
        self.enabled = True
        self.model = "gpt-5.5"
        self._codex_home = os.path.expanduser("~/.codex")

    def _find_latest_generated_image(self, session_id: str = None) -> Path | None:
        """Find the most recently generated image in codex output directory."""
        gen_dir = Path(self._codex_home) / "generated_images"
        if not gen_dir.exists():
            return None

        candidates = []
        for subdir in gen_dir.iterdir():
            if not subdir.is_dir():
                continue
            if session_id and subdir.name != session_id:
                continue
            for f in subdir.glob("*.png"):
                candidates.append((f.stat().st_mtime, f))

        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

    def _run_codex_image_gen(
        self,
        prompt: str,
        output_path: str,
        size: str = "1024x576",
    ) -> Path:
        """Call codex exec to generate image via gpt-5.5."""
        logger.info(f"Generating image via Codex {self.model}: {prompt[:60]}...")
        t0 = time.time()

        # Build codex exec command
        cmd = [
            "codex", "exec",
            "-m", self.model,
            "-s", "danger-full-access",
            "--dangerously-bypass-approvals-and-sandbox",
            "--ephemeral",
            prompt,
        ]

        # Run codex
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Extract session id from output to find the generated image
        session_id = None
        for line in result.stderr.split("\n"):
            if "session id:" in line:
                session_id = line.split("session id:")[1].strip()
                break

        # Find generated image
        generated = self._find_latest_generated_image(session_id)
        if not generated:
            # Fallback: search all recent images
            generated = self._find_latest_generated_image()

        if not generated:
            raise RuntimeError("Codex did not generate any image")

        # Copy to desired output path
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(generated, out_file)

        logger.info(f"Image generated in {time.time() - t0:.1f}s, saved to {out_file}")
        return out_file

    def generate(
        self,
        prompt: str,
        size: str = "1024x576",
        quality: str = "medium",
        output_path: str = None,
    ) -> Path:
        """Generate an image from text prompt via Codex.

        Args:
            prompt: Text description for image generation
            size: Image size, e.g. "1024x576", "1024x1024"
            quality: Image quality - "low", "medium", "high" (used in prompt)
            output_path: Where to save the image

        Returns:
            Path to the generated image file
        """
        if not self.enabled:
            raise RuntimeError("Image generation is disabled by configuration")

        # Augment prompt with quality and size hints
        full_prompt = (
            f"生成一张图片并保存到指定路径。"
            f"图片内容：{prompt}"
            f"质量要求：{quality}。"
            f"尺寸参考：{size}。"
            f"请使用 image_gen 工具生成真实的 AI 图像，"
            f"不要编写代码绘制。生成后保存到：{output_path or 'output/generated.png'}"
        )

        if output_path is None:
            output_path = "output/cover/generated.png"

        return self._run_codex_image_gen(full_prompt, output_path, size)

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
