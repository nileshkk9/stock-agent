"""Base LLM agent with common functionality."""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from src.config import config, load_prompt

logger = logging.getLogger(__name__)


class LLMAgent(ABC):
    """Abstract base for all stock analysis agents."""

    name: str = "base"

    def __init__(self):
        self.provider = config.llm.provider
        self.model = config.llm.model
        self.api_key = config.llm.api_key
        self.base_url = config.llm.base_url
        self.temperature = config.llm.temperature
        self.max_tokens = config.llm.max_tokens
        self.system_prompt = load_prompt(self.name)

    def _get_api_url(self) -> str:
        if self.provider == "openai":
            return self.base_url or "https://api.openai.com/v1/chat/completions"
        elif self.provider == "anthropic":
            return self.base_url or "https://api.anthropic.com/v1/messages"
        elif self.provider == "openrouter":
            return "https://openrouter.ai/api/v1/chat/completions"
        elif self.provider == "deepseek":
            return "https://api.deepseek.com/v1/chat/completions"
        # Custom OpenAI-compatible provider (opencode, etc.)
        if self.base_url:
            url = self.base_url.rstrip("/")
            if not url.endswith("/chat/completions"):
                url += "/chat/completions"
            return url
        return "https://api.openai.com/v1/chat/completions"

    def _get_headers(self) -> dict:
        if self.provider == "openrouter":
            return {
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/nileshkk9/stock-agent",
                "X-Title": "Stock Agent",
                "Content-Type": "application/json",
            }
        elif self.provider == "anthropic":
            return {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_messages(self, user_message: str) -> list[dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": user_message})
        return messages

    async def _call_llm(self, user_message: str) -> str:
        """Call the LLM API and return response text."""
        url = self._get_api_url()
        headers = self._get_headers()
        messages = self._build_messages(user_message)

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        if self.provider == "anthropic":
            return data["content"][0]["text"]

        # Standard OpenAI-compatible response
        choice = data["choices"][0]
        message = choice.get("message", {})
        content = message.get("content", "")

        # Handle reasoning models (deepseek-v4-pro, etc.) where content may be empty
        # and the real answer is in reasoning_content
        if not content and message.get("reasoning_content"):
            content = message["reasoning_content"]

        return content

    def call_sync(self, user_message: str) -> str:
        """Synchronous wrapper for _call_llm."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # In async context, create new loop
                import nest_asyncio
                nest_asyncio.apply()
            return asyncio.run(self._call_llm(user_message))
        except RuntimeError:
            return asyncio.run(self._call_llm(user_message))

    def _parse_json_response(self, response: str) -> dict:
        """Extract JSON from LLM response that may contain markdown."""
        # Try parsing raw response first
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding JSON object in text
        match = re.search(r"\{[\s\S]*\}", response)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(f"Could not parse JSON from response: {response[:200]}...")
        return {"error": "Failed to parse response", "raw": response[:500]}

    @abstractmethod
    def analyze(self, ticker: str, data: dict[str, Any]) -> dict[str, Any]:
        """Analyze a stock and return structured results."""
        ...
