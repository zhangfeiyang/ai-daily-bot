from unittest.mock import MagicMock, patch

from src.utils.opencli_browser import capture_screenshot_via_opencli


def test_capture_screenshot_via_opencli(tmp_path):
    output = tmp_path / "shot.png"

    open_proc = MagicMock()
    open_proc.returncode = 0
    open_proc.stdout = '{"url":"https://example.com","page":"TAB1"}'
    open_proc.stderr = ""

    shot_proc = MagicMock()
    shot_proc.returncode = 0
    shot_proc.stdout = "Screenshot saved to: shot.png"
    shot_proc.stderr = ""

    def fake_run(args, timeout=180):
        if len(args) > 1 and args[1] == "open":
            return open_proc
        if len(args) > 1 and args[1] == "screenshot":
            output.write_bytes(b"image")
            return shot_proc
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("src.utils.opencli_browser._run_opencli_browser", side_effect=fake_run):
        result = capture_screenshot_via_opencli("https://example.com", output)

    assert result == output
    assert output.read_bytes() == b"image"
