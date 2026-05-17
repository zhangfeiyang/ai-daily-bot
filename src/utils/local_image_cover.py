from __future__ import annotations

import base64
import io
import os
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _extract_base64(payload: object) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("base64", "image", "data", "result"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        images = payload.get("images")
        if isinstance(images, list) and images and isinstance(images[0], str):
            return images[0]
    raise ValueError("Local image endpoint did not return base64 image data")


def _cover_crop(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = image.convert("RGB")
    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def generate_local_claude_code_cover(
    version_text: str,
    output_dir: str | Path = "output/cover",
    endpoint: str | None = None,
    backend: str = "browser",
) -> Path:
    """Generate a WeChat-compatible Claude Code cover using the local image service."""
    version_text = version_text.strip() or "v2.x.x"
    endpoint = endpoint or os.environ.get("LOCAL_IMAGE_ENDPOINT", "http://localhost:8000/image")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt = (
        "cyberpunk developer workstation at night, terminal windows, subtle AI coding agent interface, "
        "cinematic lighting, high contrast, no readable text, clean composition for a tech article cover"
    )
    resp = requests.post(
        endpoint,
        json={"prompt": prompt, "backend": backend, "return_type": "base64"},
        timeout=180,
    )
    resp.raise_for_status()

    encoded = _extract_base64(resp.json()).strip()
    if "," in encoded and encoded[:32].lower().startswith("data:image"):
        encoded = encoded.split(",", 1)[1]
    raw = base64.b64decode(encoded)

    canvas = _cover_crop(Image.open(io.BytesIO(raw)), (900, 500)).convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (3, 7, 18, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, 0, 900, 500), fill=(5, 10, 24, 92))
    draw.rectangle((0, 340, 900, 500), fill=(5, 10, 24, 180))
    draw.rectangle((56, 60, 240, 96), fill=(233, 69, 96, 235))
    draw.rectangle((56, 106, 388, 112), fill=(74, 144, 217, 230))
    canvas = Image.alpha_composite(canvas, overlay)

    draw = ImageDraw.Draw(canvas)
    title_font = _font(76, bold=True)
    version_font = _font(38, bold=True)
    label_font = _font(22, bold=True)
    small_font = _font(18)

    draw.text((74, 66), "CLAUDE CODE", fill=(255, 255, 255), font=label_font)
    draw.text((56, 354), "Claude Code", fill=(248, 250, 252), font=title_font)
    draw.text((60, 438), f"Version Update  {version_text}", fill=(226, 232, 240), font=version_font)
    draw.text((650, 70), "AI CODING AGENT", fill=(203, 213, 225), font=small_font)

    out_path = output_dir / f"claude_code_cover_{version_text.replace('.', '_').replace('/', '_')}.jpg"
    canvas.convert("RGB").save(out_path, "JPEG", quality=92, optimize=True)
    return out_path
