from __future__ import annotations

import html
import re
from pathlib import Path


def _wrap_text(text: str, max_chars: int) -> list[str]:
    text = text.strip()
    if not text:
        return [""]
    lines = []
    current = ""
    for ch in text:
        current += ch
        if len(current) >= max_chars:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    return lines


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def generate_claude_code_cover(version_text: str, output_dir: str | Path = "output/cover") -> Path:
    """Generate a deterministic SVG cover for Claude Code version updates."""
    version_text = version_text.strip() or "v2.x.x"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "claude_code_cover.svg"

    title_lines = _wrap_text("Claude Code", 12)
    version_lines = _wrap_text(version_text, 16)

    version_badge = _escape(version_text)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="500" viewBox="0 0 900 500">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="55%" stop-color="#111827"/>
      <stop offset="100%" stop-color="#1f2937"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#e94560"/>
      <stop offset="100%" stop-color="#f59e0b"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="10" stdDeviation="16" flood-color="#000" flood-opacity="0.28"/>
    </filter>
  </defs>
  <rect width="900" height="500" fill="url(#bg)"/>
  <circle cx="740" cy="90" r="180" fill="#1d4ed8" opacity="0.16"/>
  <circle cx="120" cy="430" r="160" fill="#e94560" opacity="0.10"/>
  <path d="M80 120H820" stroke="#334155" stroke-width="2" opacity="0.45"/>
  <path d="M80 390H820" stroke="#334155" stroke-width="2" opacity="0.45"/>

  <g filter="url(#shadow)">
    <rect x="78" y="78" width="744" height="344" rx="28" fill="#0b1220" opacity="0.88" stroke="#334155"/>
    <rect x="110" y="112" width="100" height="26" rx="13" fill="url(#accent)"/>
    <text x="160" y="131" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#ffffff" font-weight="700">CLAUDE CODE</text>

    <text x="110" y="220" font-family="Arial, Helvetica, sans-serif" font-size="72" font-weight="800" fill="#f8fafc">Claude Code</text>
    <text x="110" y="275" font-family="Arial, Helvetica, sans-serif" font-size="34" fill="#cbd5e1">Version Update</text>
    <rect x="110" y="312" width="250" height="54" rx="16" fill="#111827" stroke="#475569"/>
    <text x="135" y="346" font-family="Arial, Helvetica, sans-serif" font-size="22" fill="#e2e8f0" font-weight="700">{version_badge}</text>
    <text x="110" y="392" font-family="Arial, Helvetica, sans-serif" font-size="18" fill="#94a3b8">Terminal agent, security, workflow, and UX</text>

    <rect x="560" y="120" width="182" height="230" rx="22" fill="#0f172a" stroke="#334155"/>
    <rect x="588" y="150" width="126" height="16" rx="8" fill="#334155"/>
    <rect x="588" y="182" width="96" height="16" rx="8" fill="#475569"/>
    <rect x="588" y="214" width="138" height="16" rx="8" fill="#475569"/>
    <rect x="588" y="246" width="110" height="16" rx="8" fill="#475569"/>
    <rect x="588" y="286" width="56" height="56" rx="16" fill="url(#accent)"/>
    <text x="616" y="322" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="28" fill="#ffffff" font-weight="800">#</text>
  </g>
</svg>
"""
    out_path.write_text(svg, encoding="utf-8")
    return out_path


def extract_claude_code_version(text: str) -> str:
    """Extract a Claude Code version label from free-form text."""
    text = text or ""
    m = re.search(r'(v?\d+\.\d+\.\d+(?:\.\d+)?)', text, flags=re.I)
    if m:
        return m.group(1)
    m = re.search(r'Claude Code[^0-9]{0,16}(v?\d+\.\d+\.\d+(?:\.\d+)?)', text, flags=re.I)
    if m:
        return m.group(1)
    return ""
