"""LLM Provider abstraction for model inference.

Supports Ollama as the primary provider for open-weight model serving.
Designed to be replaceable without modifying the query orchestration engine.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Structured response from the LLM."""
    content: str
    model: str
    total_duration_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw_response: dict = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None


class LLMProvider:
    """Abstraction layer for LLM inference.

    Currently supports Ollama. Add providers by extending this class.
    """

    def __init__(
        self,
        provider: str = "ollama",
        model: str = "qwen2.5-coder:7b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout: int = 120,
    ):
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    @classmethod
    def from_settings(cls) -> "LLMProvider":
        """Create an LLM provider from application settings."""
        settings = get_settings()
        return cls(
            provider=settings.llm_provider,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_request_timeout,
        )

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Generate a completion from the model.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system prompt.
            temperature: Override default temperature.
            max_tokens: Override default max tokens.
            json_mode: If True, request JSON output format.

        Returns:
            LLMResponse with the model's output.
        """
        if self.provider == "ollama":
            return self._generate_ollama(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature or self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                json_mode=json_mode,
            )
        else:
            return LLMResponse(
                content="",
                model=self.model,
                total_duration_ms=0,
                success=False,
                error=f"Unsupported provider: {self.provider}",
            )

    def _generate_ollama(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        """Call the Ollama API for text generation."""
        start_time = time.time()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        if json_mode:
            payload["format"] = "json"


        try:
            resp = self._client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            elapsed_ms = (time.time() - start_time) * 1000
            content = data.get("message", {}).get("content", "")

            return LLMResponse(
                content=content,
                model=data.get("model", self.model),
                total_duration_ms=elapsed_ms,
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                raw_response=data,
                success=True,
            )

        except httpx.TimeoutException:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error("LLM request timed out after %.1fms", elapsed_ms)
            return LLMResponse(
                content="",
                model=self.model,
                total_duration_ms=elapsed_ms,
                success=False,
                error="Model inference timed out. The model may be loading or overloaded.",
            )
        except httpx.HTTPStatusError as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error("LLM HTTP error: %s", e.response.status_code)
            return LLMResponse(
                content="",
                model=self.model,
                total_duration_ms=elapsed_ms,
                success=False,
                error=f"Model service returned HTTP {e.response.status_code}",
            )
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error("LLM request failed: %s", str(e))
            return LLMResponse(
                content="",
                model=self.model,
                total_duration_ms=elapsed_ms,
                success=False,
                error=f"Model inference unavailable: {type(e).__name__}",
            )

    def check_health(self) -> dict:
        """Check if the model service is reachable and the model is loaded."""
        try:
            if self.provider == "ollama":
                # Check Ollama is running
                resp = self._client.get(f"{self.base_url}/api/tags", timeout=5)
                resp.raise_for_status()
                models = resp.json().get("models", [])
                model_names = [m.get("name", "") for m in models]

                # Check our model is available
                model_available = any(
                    self.model in name or name.startswith(self.model.split(":")[0])
                    for name in model_names
                )

                return {
                    "status": "healthy" if model_available else "model_not_found",
                    "provider": self.provider,
                    "model": self.model,
                    "available_models": model_names,
                    "error": None if model_available else f"Model '{self.model}' not found",
                }
            return {"status": "unknown", "provider": self.provider, "error": "Unknown provider"}
        except Exception as e:
            return {
                "status": "unhealthy",
                "provider": self.provider,
                "model": self.model,
                "error": str(e),
            }

    def close(self):
        """Close the HTTP client."""
        self._client.close()
