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

    def _get_provider_config(self, provider: str) -> dict:
        return self.config.get("providers", {}).get(provider, {})

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = None) -> str:
        if self.provider == "anthropic":
            return self._generate_anthropic(system_prompt, user_prompt, temperature=temperature)
        return self._generate_openai_compatible(system_prompt, user_prompt, temperature=temperature)

    def generate_with_images(self, system_prompt: str, text: str, image_urls: list[str], provider: str = "vision") -> str:
        """Generate response with image inputs using a specified provider."""
        cfg = self._get_provider_config(provider)
        content = [{"type": "text", "text": text}]
        for url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})
        import openai
        client = openai.OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
        # Disable streaming for vision calls - some providers don't support it
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            stream=False,
        )
        return response.choices[0].message.content or ""

    def _generate_openai_compatible(self, system_prompt: str, user_prompt: str, max_tokens: int = 16384, temperature: float = None) -> str:
        import openai
        client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "stream": False,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    def _generate_anthropic(self, system_prompt: str, user_prompt: str, temperature: float = None) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = client.messages.create(**kwargs)
        return response.content[0].text
