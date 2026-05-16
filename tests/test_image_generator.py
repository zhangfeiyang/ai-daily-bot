from unittest.mock import MagicMock, patch

from src.image.generator import ImageGenerator


def test_image_generator_uses_opencli_gemini(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("IMAGE_FALLBACK_PROVIDERS", "")
    generated = tmp_path / "generated.png"
    generated.write_bytes(b"image")
    output = tmp_path / "cover.png"

    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = f'{{"status":"ok","file":"{generated}"}}'
    proc.stderr = ""

    with patch("src.image.generator.subprocess.run", return_value=proc) as mock_run:
        result = ImageGenerator().generate("AI cover", size="1024x576", output_path=str(output))

    assert result == output
    assert output.read_bytes() == b"image"
    cmd = mock_run.call_args.args[0]
    assert cmd[:3] == ["opencli", "gemini", "image"]
    assert "--rt" in cmd
    assert "16:9" in cmd
