# tests/test_video_pipeline.py
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from src.video.pipeline import VideoPipeline
from src.video.models import VideoConfig, VideoSegment, VideoMaterial, SegmentType


class TestVideoPipeline:
    def test_generate_video_from_article(self, tmp_path):
        """测试从文章生成视频"""
        # Mock所有依赖
        llm_client = Mock()
        llm_client.generate.return_value = '''{
            "segments": [
                {"text": "测试段落", "type": "with_image", "image_prompt": "test"}
            ]
        }'''

        tts_engine = Mock()
        def fake_tts(text, output_path):
            Path(output_path).write_bytes(b"fake audio")
            return output_path

        tts_engine.generate.side_effect = fake_tts

        image_gen = Mock()
        image_gen.generate.return_value = tmp_path / "image.png"

        config = VideoConfig(output_dir=tmp_path)

        # 创建模拟文章
        article_path = tmp_path / "test_article.html"
        article_path.write_text("<!-- ARTICLE_TITLE: 测试 --><html><body><p>测试段落</p></body></html>")

        # 创建模拟文件
        (tmp_path / "audio.mp3").write_bytes(b"fake")
        (tmp_path / "image.png").write_bytes(b"fake")

        with patch("src.video.material.MaterialGenerator._get_audio_duration", return_value=5.0):
            with patch("src.video.composer.Composer._run_ffmpeg"):
                pipeline = VideoPipeline(config, llm_client, tts_engine, image_gen)
                result = pipeline.generate(article_path)

        assert result is not None
        assert result.suffix == ".mp4"

    def test_generate_returns_none_on_failure(self, tmp_path):
        """测试失败时返回None"""
        llm_client = Mock()
        llm_client.generate.side_effect = Exception("LLM error")

        tts_engine = Mock()
        image_gen = Mock()
        config = VideoConfig(output_dir=tmp_path)

        article_path = tmp_path / "test.html"
        article_path.write_text("<html><body>内容</body></html>")

        pipeline = VideoPipeline(config, llm_client, tts_engine, image_gen)
        result = pipeline.generate(article_path)

        assert result is None

    def test_from_config_factory(self):
        """测试工厂方法"""
        with patch("src.video.pipeline.load_config") as mock_load:
            mock_load.side_effect = lambda name: {
                "llm": {"default": "openai", "providers": {"openai": {"api_key": "test"}}},
                "tts": {"edge-tts": {"voice": "zh-CN-YunxiNeural"}},
            }.get(name, {})

            with patch("src.video.pipeline.LLMClient") as mock_llm:
                with patch("src.video.pipeline.TTSEngine") as mock_tts:
                    with patch("src.video.pipeline.ImageGenerator") as mock_img:
                        pipeline = VideoPipeline.from_config()

                        assert pipeline is not None
