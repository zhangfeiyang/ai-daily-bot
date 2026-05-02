# tests/test_video_composer.py
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from src.video.composer import Composer
from src.video.models import VideoSegment, VideoMaterial, VideoConfig, SegmentType


class TestComposer:
    def test_create_text_clip_command(self, tmp_path):
        """测试纯文字片段命令构建"""
        config = VideoConfig(output_dir=tmp_path)
        composer = Composer(config)

        segment = VideoSegment(id=1, text="测试文本", segment_type=SegmentType.TEXT_ONLY, image_prompt=None, duration=5.0)
        material = VideoMaterial(
            segment_id=1,
            audio_path=tmp_path / "audio.mp3",
            image_path=None,
            subtitle_srt=tmp_path / "subtitle.srt"
        )

        # 创建模拟音频文件
        (tmp_path / "audio.mp3").write_bytes(b"fake audio")
        (tmp_path / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:05,000\n测试文本\n")

        cmd = composer._build_text_clip_command(material, segment, tmp_path / "clip.mp4")

        assert "ffmpeg" in cmd[0] or "ffmpeg" in " ".join(cmd)
        assert "drawtext" in " ".join(cmd) or "ass" in " ".join(cmd)

    def test_create_image_clip_command(self, tmp_path):
        """测试配图片段命令构建"""
        config = VideoConfig(output_dir=tmp_path)
        composer = Composer(config)

        segment = VideoSegment(id=2, text="配图文本", segment_type=SegmentType.WITH_IMAGE, image_prompt="test", duration=5.0)
        material = VideoMaterial(
            segment_id=2,
            audio_path=tmp_path / "audio.mp3",
            image_path=tmp_path / "image.png",
            subtitle_srt=tmp_path / "subtitle.srt"
        )

        # 创建模拟文件
        (tmp_path / "audio.mp3").write_bytes(b"fake audio")
        (tmp_path / "image.png").write_bytes(b"fake image")
        (tmp_path / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:05,000\n配图文本\n")

        cmd = composer._build_image_clip_command(material, segment, tmp_path / "clip.mp4")

        assert "ffmpeg" in " ".join(cmd)
        assert str(material.image_path) in " ".join(cmd)

    def test_concat_clips_command(self, tmp_path):
        """测试拼接命令构建"""
        config = VideoConfig(output_dir=tmp_path)
        composer = Composer(config)

        clip_paths = [tmp_path / "clip1.mp4", tmp_path / "clip2.mp4"]
        for clip in clip_paths:
            clip.write_bytes(b"fake video")

        cmd = composer._build_concat_command(clip_paths, tmp_path / "final.mp4")

        assert "concat" in " ".join(cmd)
        assert "ffmpeg" in " ".join(cmd)

    @patch("subprocess.run")
    def test_compose_runs_ffmpeg(self, mock_run, tmp_path):
        """测试compose方法调用FFmpeg"""
        mock_run.return_value = MagicMock(returncode=0)

        config = VideoConfig(output_dir=tmp_path)
        composer = Composer(config)

        segments = [
            VideoSegment(id=0, text="测试", segment_type=SegmentType.TEXT_ONLY, image_prompt=None, duration=3.0)
        ]
        materials = [
            VideoMaterial(
                segment_id=0,
                audio_path=tmp_path / "audio.mp3",
                image_path=None,
                subtitle_srt=tmp_path / "subtitle.srt"
            )
        ]

        # 创建模拟文件
        (tmp_path / "audio.mp3").write_bytes(b"fake")
        (tmp_path / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:03,000\n测试\n")

        output_path = tmp_path / "final.mp4"
        result = composer.compose(materials, segments, output_path)

        assert mock_run.called
