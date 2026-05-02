# tests/test_video_models.py
import pytest
from pathlib import Path
from src.video.models import VideoSegment, VideoMaterial, VideoConfig, SegmentType


class TestSegmentType:
    def test_segment_type_values(self):
        assert SegmentType.TEXT_ONLY.value == "text_only"
        assert SegmentType.WITH_IMAGE.value == "with_image"


class TestVideoSegment:
    def test_create_text_only_segment(self):
        seg = VideoSegment(id=1, text="测试文本", segment_type=SegmentType.TEXT_ONLY, image_prompt=None)
        assert seg.id == 1
        assert seg.text == "测试文本"
        assert seg.segment_type == SegmentType.TEXT_ONLY
        assert seg.image_prompt is None
        assert seg.duration is None

    def test_create_with_image_segment(self):
        seg = VideoSegment(id=2, text="配图文本", segment_type=SegmentType.WITH_IMAGE, image_prompt="AI technology")
        assert seg.segment_type == SegmentType.WITH_IMAGE
        assert seg.image_prompt == "AI technology"

    def test_segment_with_duration(self):
        seg = VideoSegment(id=3, text="测试", segment_type=SegmentType.TEXT_ONLY, image_prompt=None, duration=5.5)
        assert seg.duration == 5.5


class TestVideoMaterial:
    def test_create_material_with_image(self):
        mat = VideoMaterial(
            segment_id=1,
            audio_path=Path("output/audio.mp3"),
            image_path=Path("output/image.png"),
            subtitle_srt=Path("output/subtitle.srt")
        )
        assert mat.segment_id == 1
        assert mat.image_path is not None

    def test_create_material_text_only(self):
        mat = VideoMaterial(
            segment_id=2,
            audio_path=Path("output/audio.mp3"),
            image_path=None,
            subtitle_srt=Path("output/subtitle.srt")
        )
        assert mat.image_path is None


class TestVideoConfig:
    def test_default_config(self):
        config = VideoConfig()
        assert config.output_dir == Path("output/videos")
        assert config.video_width == 1280
        assert config.video_height == 720
        assert config.fps == 30

    def test_custom_config(self):
        config = VideoConfig(output_dir=Path("custom"), video_width=1920, video_height=1080)
        assert config.video_width == 1920
        assert config.video_height == 1080