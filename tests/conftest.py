import pytest


@pytest.fixture(autouse=True)
def disable_external_minimax_image_understanding(monkeypatch):
    monkeypatch.setenv("ENABLE_MINIMAX_IMAGE_UNDERSTANDING", "0")
