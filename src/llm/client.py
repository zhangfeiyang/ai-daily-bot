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

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.provider == "anthropic":
            return self._generate_anthropic(system_prompt, user_prompt)
        return self._generate_openai_compatible(system_prompt, user_prompt)

    def generate_with_images(self, system_prompt: str, text: str, image_urls: list[str], provider: str = "vision") -> str:
        """Generate response with image inputs using a specified provider."""
        cfg = self._get_provider_config(provider)
        content = [{"type": "text", "text": text}]
        for url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})
        import openai
        client = openai.OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            stream=True,
        )
        chunks = []
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
        return "".join(chunks)

    def _generate_openai_compatible(self, system_prompt: str, user_prompt: str) -> str:
        import openai
        client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
        )
        chunks = []
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
        return "".join(chunks)

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
