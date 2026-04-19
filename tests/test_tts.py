# tests/test_tts.py
import os
import tempfile
from unittest.mock import patch, MagicMock
from src.tts.engine import TTSEngine


def test_tts_engine_init():
    config = {
        "default": "edge-tts",
        "edge-tts": {
            "voice": "zh-CN-YunxiNeural",
            "rate": "+0%",
            "output_format": "mp3",
        },
    }
    engine = TTSEngine(config)
    assert engine.voice == "zh-CN-YunxiNeural"
    assert engine.rate == "+0%"


def test_tts_engine_generate():
    config = {
        "default": "edge-tts",
        "edge-tts": {
            "voice": "zh-CN-YunxiNeural",
            "rate": "+0%",
            "output_format": "mp3",
        },
    }
    engine = TTSEngine(config)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "test.mp3")
        # Mock edge_tts.Communicate to create a fake file
        mock_communicate = MagicMock()

        async def fake_save(path, **kwargs):
            with open(path, "wb") as f:
                f.write(b"fake mp3 content")

        mock_communicate.save = fake_save

        with patch("src.tts.engine.edge_tts.Communicate", return_value=mock_communicate):
            result = engine.generate("测试文本", output_path)
            assert os.path.exists(result)
            assert os.path.getsize(result) > 0
