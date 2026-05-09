# tests/test_video_material.py
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from src.video.material import MaterialGenerator
from src.video.models import VideoSegment, VideoMaterial, SegmentType


class TestMaterialGenerator:
    def test_generate_audio_for_segment(self, tmp_path):
        """测试为段落生成音频"""
        tts_engine = Mock()
        expected_audio = tmp_path / "segment_1.mp3"
        expected_audio.write_bytes(b"fake audio")
        tts_engine.generate.return_value = str(expected_audio)

        image_gen = Mock()

        generator = MaterialGenerator(tts_engine, image_gen)
        segment = VideoSegment(id=1, text="测试文本", segment_type=SegmentType.TEXT_ONLY, image_prompt=None)

        audio_path = generator._generate_audio(segment, tmp_path)

        assert audio_path == tmp_path / "segment_1.mp3"
        tts_engine.generate.assert_called_once_with("测试文本", str(tmp_path / "segment_1.mp3"))

    def test_generate_audio_requires_output_file(self, tmp_path):
        """测试TTS没有生成文件时抛出明确错误"""
        tts_engine = Mock()
        tts_engine.generate.return_value = str(tmp_path / "missing.mp3")
        image_gen = Mock()

        generator = MaterialGenerator(tts_engine, image_gen)
        segment = VideoSegment(id=1, text="测试文本", segment_type=SegmentType.TEXT_ONLY, image_prompt=None)

        with pytest.raises(RuntimeError, match="TTS did not create audio file"):
            generator._generate_audio(segment, tmp_path)

    def test_generate_image_for_segment(self, tmp_path):
        """测试为段落生成图片"""
        tts_engine = Mock()
        image_gen = Mock()
        image_gen.generate.return_value = tmp_path / "image.png"

        generator = MaterialGenerator(tts_engine, image_gen)
        segment = VideoSegment(id=2, text="配图文本", segment_type=SegmentType.WITH_IMAGE, image_prompt="AI technology")

        image_path = generator._generate_image(segment, tmp_path)

        assert image_path == tmp_path / "segment_2.png"
        image_gen.generate.assert_called_once()

    def test_skip_image_for_text_only(self, tmp_path):
        """测试纯文字段落不生成图片"""
        tts_engine = Mock()
        image_gen = Mock()

        generator = MaterialGenerator(tts_engine, image_gen)
        segment = VideoSegment(id=3, text="纯文字", segment_type=SegmentType.TEXT_ONLY, image_prompt=None)

        image_path = generator._generate_image(segment, tmp_path)

        assert image_path is None
        image_gen.generate.assert_not_called()

    def test_generate_subtitle_srt(self, tmp_path):
        """测试生成SRT字幕文件"""
        tts_engine = Mock()
        image_gen = Mock()

        generator = MaterialGenerator(tts_engine, image_gen)
        segment = VideoSegment(id=1, text="这是一段测试文本", segment_type=SegmentType.TEXT_ONLY, image_prompt=None, duration=3.0)

        srt_path = generator._generate_subtitle(segment, 3.0, tmp_path)

        assert srt_path.exists()
        content = srt_path.read_text()
        assert "1" in content  # 序号
        # SRT splits text into lines, so check that each part is present
        assert "这是一段测" in content or "这是一段" in content  # First line (5 chars)
        assert "试文本" in content  # Second line

    def test_generate_all_materials(self, tmp_path):
        """测试生成所有素材"""
        tts_engine = Mock()
        def fake_tts(text, output_path):
            Path(output_path).write_bytes(b"fake audio")
            return output_path

        tts_engine.generate.side_effect = fake_tts

        image_gen = Mock()
        image_gen.generate.return_value = tmp_path / "image.png"

        # Mock audio duration
        with patch("src.video.material.MaterialGenerator._get_audio_duration", return_value=5.0):
            generator = MaterialGenerator(tts_engine, image_gen)
            segments = [
                VideoSegment(id=0, text="第一段", segment_type=SegmentType.WITH_IMAGE, image_prompt="test"),
                VideoSegment(id=1, text="第二段", segment_type=SegmentType.TEXT_ONLY, image_prompt=None),
            ]

            materials = generator.generate(segments, tmp_path)

            assert len(materials) == 2
            assert materials[0].image_path is not None
            assert materials[1].image_path is None
