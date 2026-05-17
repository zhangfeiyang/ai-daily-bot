from unittest.mock import MagicMock, patch

from src.image.generator import ImageGenerator


def _make_opencli_process(returncode: int = 0, stdout: str = "", stderr: str = "", poll_sequence=None):
    proc = MagicMock()
    if poll_sequence is None:
        poll_sequence = [returncode]
    sequence = list(poll_sequence)

    def _poll():
        if sequence:
            return sequence.pop(0)
        return returncode

    proc.poll.side_effect = _poll
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    return proc


def test_image_generator_uses_opencli_gemini(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("IMAGE_FALLBACK_PROVIDERS", "")
    monkeypatch.setenv("IMAGE_PROVIDER_ROTATION_STATE", str(tmp_path / "rotation.json"))
    monkeypatch.chdir(tmp_path)
    generated = tmp_path / "output" / "generated_images" / "gemini.png"
    generated.parent.mkdir(parents=True, exist_ok=True)
    output = tmp_path / "cover.png"

    proc = _make_opencli_process(returncode=0, stdout=f'{{"status":"ok","file":"{generated}"}}', poll_sequence=[None])

    def fake_popen(*args, **kwargs):
        generated.write_bytes(b"image")
        return proc

    with patch("src.image.generator.subprocess.Popen", side_effect=fake_popen) as mock_run:
        result = ImageGenerator().generate("AI cover", size="1024x576", output_path=str(output))

    assert result == output
    assert output.read_bytes() == b"image"
    cmd = mock_run.call_args.args[0]
    assert cmd[:3] == ["opencli", "gemini", "image"]
    assert "--rt" in cmd
    assert "16:9" in cmd
    proc.terminate.assert_called_once()


def test_opencli_placeholder_file_waits_for_late_gemini_file(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("IMAGE_FALLBACK_PROVIDERS", "")
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / "output" / "generated_images"
    output_dir.mkdir(parents=True)
    generated = output_dir / "gemini.png"
    output = tmp_path / "cover.png"

    gemini_proc = _make_opencli_process(returncode=0, stdout='{"status":"ok","file":"\\ud83d\\udcc1 -"}')

    def fake_popen(*args, **kwargs):
        return gemini_proc

    def fake_wait(*args, **kwargs):
        generated.write_bytes(b"image")
        return generated

    with patch.object(ImageGenerator, "_next_rotated_primary_provider", return_value="gemini"), \
         patch("src.image.generator.subprocess.Popen", side_effect=fake_popen) as mock_run, \
         patch.object(ImageGenerator, "_wait_for_opencli_image_file", side_effect=fake_wait):
        result = ImageGenerator().generate("AI cover", size="1024x576", output_path=str(output))

    assert result == output
    assert output.read_bytes() == b"image"
    assert mock_run.call_count == 1
    assert mock_run.call_args.args[0][:3] == ["opencli", "gemini", "image"]


def test_opencli_empty_result_waits_for_late_file(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "doubao")
    monkeypatch.setenv("IMAGE_FALLBACK_PROVIDERS", "")
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / "output" / "generated_images"
    output_dir.mkdir(parents=True)
    generated = output_dir / "doubao.png"
    output = tmp_path / "cover.png"

    proc = _make_opencli_process(
        returncode=66,
        stderr="ok: false\nerror:\n  code: EMPTY_RESULT\n  message: doubao image returned no data",
    )

    def fake_popen(*args, **kwargs):
        return proc

    def fake_wait(*args, **kwargs):
        generated.write_bytes(b"image")
        return generated

    with patch.object(ImageGenerator, "_next_rotated_primary_provider", return_value="doubao"), \
         patch("src.image.generator.subprocess.Popen", side_effect=fake_popen) as mock_run, \
         patch.object(ImageGenerator, "_wait_for_opencli_image_file", side_effect=fake_wait):
        result = ImageGenerator().generate("AI cover", size="1024x576", output_path=str(output))

    assert result == output
    assert output.read_bytes() == b"image"
    assert mock_run.call_count == 1
    assert mock_run.call_args.args[0][:3] == ["opencli", "doubao", "image"]


def test_opencli_icon_prefixed_file_path_is_normalized(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("IMAGE_FALLBACK_PROVIDERS", "")
    generated = tmp_path / "output" / "generated_images" / "gemini.png"
    generated.parent.mkdir(parents=True)
    output = tmp_path / "cover.png"

    proc = _make_opencli_process(returncode=0, stdout='{"status":"ok","file":"\\ud83d\\udcc1 output/generated_images/gemini.png"}')

    def fake_wait(*args, **kwargs):
        generated.write_bytes(b"image")
        return generated

    with patch("src.image.generator.subprocess.Popen", return_value=proc), \
         patch.object(ImageGenerator, "_wait_for_opencli_image_file", side_effect=fake_wait):
        result = ImageGenerator().generate("AI cover", size="1024x576", output_path=str(output))

    assert result == output
    assert output.read_bytes() == b"image"


def test_wait_for_opencli_image_file_detects_late_file(tmp_path):
    generator = ImageGenerator()
    generator.opencli_grace_period = 1
    generator.opencli_poll_interval = 0

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    late_file = output_dir / "late.png"
    late_file.write_bytes(b"image")

    result = generator._wait_for_opencli_image_file(output_dir, existing_files=set())

    assert result == late_file


def test_image_generator_defaults_wait_longer(monkeypatch):
    monkeypatch.delenv("OPENCLI_IMAGE_TIMEOUT", raising=False)
    monkeypatch.delenv("OPENCLI_IMAGE_GRACE_PERIOD", raising=False)

    generator = ImageGenerator()

    assert generator.opencli_timeout == 180
    assert generator.opencli_grace_period == 180


def test_image_generator_rotates_gemini_and_doubao_first(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("IMAGE_FALLBACK_PROVIDERS", "doubao,chatgpt")
    monkeypatch.setenv("IMAGE_PRIMARY_PROVIDER_STRATEGY", "rotate")

    generator = ImageGenerator()
    with patch.object(ImageGenerator, "_next_rotated_primary_provider", return_value="doubao"):
        ordered = generator._ordered_providers()

    assert ordered[:3] == ["doubao", "gemini", "chatgpt"]


def test_doubao_uses_opencli_not_minimax(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "doubao")
    monkeypatch.setenv("IMAGE_FALLBACK_PROVIDERS", "")
    generator = ImageGenerator()

    with patch.object(generator, "_call_opencli_image", return_value={"provider": "doubao", "file": "x", "raw": ""}) as opencli_mock, \
         patch.object(generator, "_call_minimax_api", return_value={"data": {"image_urls": ["https://example.com"]}}) as minimax_mock:
        result = generator._call_api_for_provider("doubao", "prompt")

    assert result["provider"] == "doubao"
    opencli_mock.assert_called_once()
    minimax_mock.assert_not_called()


def test_generate_cover_keeps_long_article_context(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("IMAGE_FALLBACK_PROVIDERS", "")
    monkeypatch.setenv("IMAGE_PROVIDER_ROTATION_STATE", str(tmp_path / "rotation.json"))
    generated = tmp_path / "generated.png"
    generated.write_bytes(b"image")
    output = tmp_path / "cover.png"

    proc = _make_opencli_process(returncode=0, stdout=f'{{"status":"ok","file":"{generated}"}}')

    long_summary = "开头信息 " + ("中间上下文 " * 40) + "结尾关键提示词"

    with patch("src.image.generator.subprocess.Popen", return_value=proc) as mock_run:
        ImageGenerator().generate_cover("AI 重大新闻", long_summary, output_path=str(output))

    prompt = mock_run.call_args.args[0][3]
    assert "AI 重大新闻" in prompt
    assert "结尾关键提示词" in prompt
    assert "Context:" not in prompt


def test_generate_illustration_keeps_section_context(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("IMAGE_FALLBACK_PROVIDERS", "")
    monkeypatch.setenv("IMAGE_PROVIDER_ROTATION_STATE", str(tmp_path / "rotation.json"))
    generated = tmp_path / "generated.png"
    generated.write_bytes(b"image")
    output = tmp_path / "illustration.png"

    proc = _make_opencli_process(returncode=0, stdout=f'{{"status":"ok","file":"{generated}"}}')

    long_context = "段落开始 " + ("细节上下文 " * 50) + "结尾细节"

    with patch("src.image.generator.subprocess.Popen", return_value=proc) as mock_run:
        ImageGenerator().generate_illustration(
            "模型发布",
            long_context,
            output_path=str(output),
            article_title="OpenAI 发布会",
            source_name="X",
        )

    prompt = mock_run.call_args.args[0][3]
    assert "模型发布" in prompt
    assert "OpenAI 发布会" in prompt
    assert "结尾细节" in prompt
