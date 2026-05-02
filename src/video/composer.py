import subprocess
import tempfile
from pathlib import Path
from loguru import logger

from src.video.models import VideoSegment, VideoMaterial, VideoConfig, SegmentType


class Composer:
    """FFmpeg视频合成器"""

    def __init__(self, config: VideoConfig):
        self.config = config

    def compose(self, materials: list[VideoMaterial], segments: list[VideoSegment], output_path: Path) -> Path:
        """合成最终视频"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        clips_dir = output_path.parent / "clips"
        clips_dir.mkdir(exist_ok=True)

        clip_paths = []

        for mat, seg in zip(materials, segments):
            clip_path = clips_dir / f"clip_{seg.id}.mp4"

            try:
                if mat.image_path and mat.image_path.exists():
                    self._create_image_clip(mat, seg, clip_path)
                else:
                    self._create_text_clip(mat, seg, clip_path)

                clip_paths.append(clip_path)
                logger.info(f"Created clip {seg.id}")
            except Exception as e:
                logger.error(f"Failed to create clip {seg.id}: {e}")
                continue

        if not clip_paths:
            raise RuntimeError("No clips were created")

        # 拼接所有片段
        self._concat_clips(clip_paths, output_path)
        logger.info(f"Video composed: {output_path}")

        return output_path

    def _create_text_clip(self, material: VideoMaterial, segment: VideoSegment, output_path: Path) -> None:
        """创建纯文字视频片段"""
        cmd = self._build_text_clip_command(material, segment, output_path)
        self._run_ffmpeg(cmd)

    def _create_image_clip(self, material: VideoMaterial, segment: VideoSegment, output_path: Path) -> None:
        """创建配图视频片段"""
        cmd = self._build_image_clip_command(material, segment, output_path)
        self._run_ffmpeg(cmd)

    def _build_text_clip_command(self, material: VideoMaterial, segment: VideoSegment, output_path: Path) -> list[str]:
        """构建纯文字片段FFmpeg命令"""
        duration = segment.duration or 5.0
        text = segment.text.replace("'", "'\\''")  # 转义单引号

        # 使用drawtext滤镜显示文字
        return [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=white:s={self.config.video_width}x{self.config.video_height}:d={duration}",
            "-i", str(material.audio_path),
            "-vf", f"drawtext=text='{text}':fontsize={self.config.subtitle_fontsize}:fontcolor=black:x=(w-text_w)/2:y=(h-text_h)/2",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-t", str(duration),
            str(output_path)
        ]

    def _build_image_clip_command(self, material: VideoMaterial, segment: VideoSegment, output_path: Path) -> list[str]:
        """构建配图片段FFmpeg命令"""
        duration = segment.duration or 5.0

        # 图片缩放 + 音频 + 字幕
        return [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(material.image_path),
            "-i", str(material.audio_path),
            "-vf", f"scale={self.config.video_width}:{self.config.video_height}:force_original_aspect_ratio=decrease,pad={self.config.video_width}:{self.config.video_height}:(ow-iw)/2:(oh-ih)/2,subtitles={str(material.subtitle_srt)}:force_style='FontName={self.config.subtitle_font},FontSize={self.config.subtitle_fontsize},PrimaryColour=&H{self._color_to_ass(self.config.subtitle_color)},OutlineColour=&H000000,BackColour=&H{self._color_to_ass_bg(self.config.subtitle_bg)}'",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            str(output_path)
        ]

    def _build_concat_command(self, clip_paths: list[Path], output_path: Path) -> list[str]:
        """构建拼接FFmpeg命令"""
        # 创建concat文件列表
        concat_file = output_path.parent / "concat.txt"
        with open(concat_file, "w") as f:
            for clip in clip_paths:
                f.write(f"file '{clip}'\n")

        return [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path)
        ]

    def _concat_clips(self, clip_paths: list[Path], output_path: Path) -> None:
        """拼接视频片段"""
        cmd = self._build_concat_command(clip_paths, output_path)
        self._run_ffmpeg(cmd)

    def _run_ffmpeg(self, cmd: list[str]) -> None:
        """执行FFmpeg命令"""
        logger.debug(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed: {result.stderr[:500]}")

    def _color_to_ass(self, color: str) -> str:
        """将颜色名称转换为ASS格式（BGR）"""
        colors = {
            "white": "FFFFFF",
            "black": "000000",
            "yellow": "00FFFF",
            "red": "0000FF",
            "green": "00FF00",
            "blue": "FF0000",
        }
        return colors.get(color.lower(), "FFFFFF")

    def _color_to_ass_bg(self, bg: str) -> str:
        """解析背景色（带透明度）"""
        # 格式: black@0.5
        if "@" in bg:
            color, alpha = bg.split("@")
            alpha_hex = int(float(alpha) * 255)
            return f"{self._color_to_ass(color)}&{alpha_hex:02X}"
        return self._color_to_ass(bg) + "&80"
