# tests/test_prompts.py
import os
import tempfile
from src.llm.prompts import load_prompt


def test_load_prompt_renders_template():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.md")
        with open(path, "w") as f:
            f.write("Hello {{name}}, today is {{date}}.")
        result = load_prompt("test", name="World", date="2026-04-19", prompts_dir=tmpdir)
        assert result == "Hello World, today is 2026-04-19."


def test_load_prompt_missing_var_keeps_placeholder():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.md")
        with open(path, "w") as f:
            f.write("Hello {{name}}, {{missing}}.")
        result = load_prompt("test", name="World", prompts_dir=tmpdir)
        assert result == "Hello World, {{missing}}."
