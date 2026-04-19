# src/llm/prompts.py
import re
from pathlib import Path


def load_prompt(template_name: str, prompts_dir: str = None, **kwargs) -> str:
    if prompts_dir is None:
        prompts_dir = Path(__file__).parent.parent.parent / "prompts"
    else:
        prompts_dir = Path(prompts_dir)
    path = prompts_dir / f"{template_name}.md"
    template = path.read_text(encoding="utf-8")

    def replacer(match):
        key = match.group(1)
        return str(kwargs.get(key, match.group(0)))

    return re.sub(r"\{\{(\w+)\}\}", replacer, template)
