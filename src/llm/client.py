# src/llm/client.py
from loguru import logger


class LLMClient:
    def __init__(self, config: dict):
        self.config = config
        self.provider = config.get("default", "openai")
        self._provider_config = config.get("providers", {}).get(self.provider, {})
        self.api_key = self._provider_config.get("api_key", "")
        self.base_url = self._provider_config.get("base_url", "")
        self.model = self._provider_config.get("model", "")

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.provider == "anthropic":
            return self._generate_anthropic(system_prompt, user_prompt)
        return self._generate_openai_compatible(system_prompt, user_prompt)

    def _generate_openai_compatible(self, system_prompt: str, user_prompt: str) -> str:
        import openai
        client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content

    def _generate_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text
