# src/video/material.py
import subprocess
from pathlib import Path
from loguru import logger

from src.video.models import VideoSegment, VideoMaterial, SegmentType
from src.tts.engine import TTSEngine
from src.image.generator import ImageGenerator


class MaterialGenerator:
    """素材生成器：TTS音频 + Codex图片 + SRT字幕"""

    def __init__(self, tts_engine: TTSEngine, image_generator: ImageGenerator):
        self.tts = tts_engine
        self.image_gen = image_generator

    def generate(self, segments: list[VideoSegment], output_dir: Path) -> list[VideoMaterial]:
        """为所有段落生成素材"""
        output_dir.mkdir(parents=True, exist_ok=True)
        materials = []

        for seg in segments:
            try:
                # 生成音频
                audio_path = self._generate_audio(seg, output_dir)

                # 获取音频时长
                duration = self._get_audio_duration(audio_path)
                seg.duration = duration

                # 生成图片（仅配图段落）
                image_path = None
                if seg.segment_type == SegmentType.WITH_IMAGE:
                    image_path = self._generate_image(seg, output_dir)

                # 生成字幕
                srt_path = self._generate_subtitle(seg, duration, output_dir)

                materials.append(VideoMaterial(
                    segment_id=seg.id,
                    audio_path=audio_path,
                    image_path=image_path,
                    subtitle_srt=srt_path
                ))
                logger.info(f"Generated materials for segment {seg.id}")

            except Exception as e:
                logger.error(f"Failed to generate materials for segment {seg.id}: {e}")
                raise

        return materials

    def _generate_audio(self, segment: VideoSegment, output_dir: Path) -> Path:
        """调用TTS生成音频"""
        audio_path = output_dir / f"segment_{segment.id}.mp3"
        self.tts.generate(segment.text, str(audio_path))
        return audio_path

    def _generate_image(self, segment: VideoSegment, output_dir: Path) -> Path | None:
        """调用Codex生成配图"""
        if segment.image_prompt is None:
            return None

        try:
            image_path = output_dir / f"segment_{segment.id}.png"
            self.image_gen.generate(
                prompt=segment.image_prompt,
                size="1280x720",
                quality="medium",
                output_path=str(image_path)
            )
            return image_path
        except Exception as e:
            logger.warning(f"Image generation failed for segment {segment.id}: {e}, falling back to text only")
            return None

    def _generate_subtitle(self, segment: VideoSegment, duration: float, output_dir: Path) -> Path:
        """生成SRT字幕文件"""
        srt_path = output_dir / f"segment_{segment.id}.srt"
        text = segment.text

        # 计算每字平均时长
        char_count = len(text)
        char_duration = duration / char_count if char_count > 0 else 0.1

        # 生成字幕块（每行5个字）
        chars_per_line = 5
        lines = [text[i:i+chars_per_line] for i in range(0, len(text), chars_per_line)]

        srt_content = []
        current_time = 0.0

        for i, line in enumerate(lines):
            line_duration = len(line) * char_duration
            start_time = current_time
            end_time = current_time + line_duration

            srt_content.append(f"{i + 1}")
            srt_content.append(f"{self._format_srt_time(start_time)} --> {self._format_srt_time(end_time)}")
            srt_content.append(line)
            srt_content.append("")

            current_time = end_time

        srt_path.write_text("\n".join(srt_content), encoding="utf-8")
        return srt_path

    def _format_srt_time(self, seconds: float) -> str:
        """格式化SRT时间戳"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _get_audio_duration(self, audio_path: Path) -> float:
        """获取音频时长（秒）"""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
                capture_output=True,
                text=True,
                check=True
            )
            return float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Failed to get audio duration: {e}, using estimate")
            # 估算：每100字约10秒
            return 10.0