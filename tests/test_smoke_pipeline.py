from pathlib import Path

from src.testing.smoke import run_smoke_pipeline


def test_mocked_pipeline_smoke(tmp_path: Path):
    result = run_smoke_pipeline(tmp_path)

    assert result.success is True
    assert Path(result.article_path).exists()
    assert result.llm_generate_calls >= 2
    assert result.tts_calls == 0
    assert result.publish_calls == 0
    assert result.inserted_images >= 2
    assert result.inserted_videos >= 1
    assert result.thumb_media_id == "thumb_smoke_001"
    assert result.audio_paths == []
    assert "OpenAI Codex" in result.html
    assert "DeepSeek" in result.html
    assert "Google Gemini" in result.html
