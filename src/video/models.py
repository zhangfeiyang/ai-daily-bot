from dataclasses import dataclass
from pathlib import Path
from enum import Enum


class SegmentType(Enum):
    """视频段落类型"""
    TEXT_ONLY = "text_only"      # 纯文字页
    WITH_IMAGE = "with_image"    # 配图段落


@dataclass
class VideoSegment:
    """单个视频段落"""
    id: int
    text: str                    # 段落文本内容
    segment_type: SegmentType    # 段落类型
    image_prompt: str | None     # 图片生成提示词（LLM生成）
    duration: float | None = None  # 音频时长（秒），素材生成后填充


@dataclass
class VideoMaterial:
    """单个段落的素材"""
    segment_id: int
    audio_path: Path             # TTS生成的音频
    image_path: Path | None      # 生成的配图（纯文字页为None）
    subtitle_srt: Path           # 字幕SRT文件


@dataclass
class VideoConfig:
    """视频配置"""
    output_dir: Path = Path("output/videos")
    video_width: int = 1280
    video_height: int = 720
    fps: int = 30
    subtitle_font: str = "NotoSansSC-Regular.ttf"
    subtitle_fontsize: int = 36
    subtitle_color: str = "white"
    subtitle_bg: str = "black@0.5"