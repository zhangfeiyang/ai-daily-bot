# tests/test_config.py
import os
import tempfile
import yaml
from src.config import load_config


def test_load_config_reads_yaml():
    with tempfile.TemporaryDirectory() as tmpdir:
        llm_path = os.path.join(tmpdir, "llm.yaml")
        with open(llm_path, "w") as f:
            yaml.dump({"default": "openai", "providers": {"openai": {"model": "gpt-4o"}}}, f)
        config = load_config("llm", config_dir=tmpdir)
        assert config["default"] == "openai"
        assert config["providers"]["openai"]["model"] == "gpt-4o"


def test_load_config_env_substitution(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.yaml")
        with open(path, "w") as f:
            yaml.dump({"key": "${TEST_API_KEY}"}, f)
        config = load_config("test", config_dir=tmpdir)
        assert config["key"] == "sk-test-123"


def test_load_config_missing_file():
    config = load_config("nonexistent", config_dir="/tmp/empty_xyz")
    assert config == {}
