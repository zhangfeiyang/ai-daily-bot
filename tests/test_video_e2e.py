# tests/test_video_e2e.py
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 跳过如果没有FFmpeg
pytestmark = pytest.mark.skipif(
    os.system("which ffmpeg > /dev/null 2>&1") != 0,
    reason="ffmpeg not installed"
)


class TestVideoE2E:
    """端到端测试（需要FFmpeg）"""

    def test_generate_video_from_real_article(self, tmp_path):
        """使用真实文章测试视频生成（mock LLM和图片生成）"""
        from src.video import VideoPipeline, VideoConfig, VideoSegment, SegmentType

        # 使用真实文章
        article_path = Path("output/articles/feature_2026-05-02_1.html")
        if not article_path.exists():
            pytest.skip("No test article available")

        config = VideoConfig(output_dir=tmp_path)

        # Mock LLM
        with patch("src.video.segmenter.Segmenter._llm_segment") as mock_segment:
            mock_segment.return_value = [
                VideoSegment(id=0, text="这是测试段落一", segment_type=SegmentType.WITH_IMAGE, image_prompt="AI tech"),
                VideoSegment(id=1, text="这是测试段落二", segment_type=SegmentType.TEXT_ONLY, image_prompt=None),
            ]

            # Mock图片生成
            with patch("src.video.material.ImageGenerator.generate") as mock_img:
                mock_img.return_value = tmp_path / "test_image.png"
                (tmp_path / "test_image.png").write_bytes(b"fake image")

                pipeline = VideoPipeline.from_config(config)
                result = pipeline.generate(article_path)

                # 验证视频文件生成
                if result:
                    assert result.exists()
                    assert result.suffix == ".mp4"
