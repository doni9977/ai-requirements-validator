"""Клиент для работы с Gemini API на базе официального SDK google-genai."""

from __future__ import annotations

import json
import random
import re
import threading
import time
from typing import Any, Type, TypeVar

from google import genai
from pydantic import BaseModel

from .config import Config

T = TypeVar("T", bound=BaseModel)

DEPRECATED_MODEL_PREFIXES = ("gemini-1.5", "gemini-2.0", "gemini-2.5")

# Упорядоченная цепочка актуальных моделей для автоматического failover при 503 / 429 / 404
FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-4-hydrogen",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemma-4-26b-a4b-it",
    "gemma-4-31b-it",
)


class LLMClient:
    """
    Потокобезопасный клиент Gemini API на базе официального SDK `google-genai`.
    Использует Interactions API (`client.interactions.create`) со строгим Structured Output
    и автоматическим failover между моделями при временной перегрузке (503) или квотах (429).
    """

    def __init__(self, config: Config):
        self.config = config
        self.primary_model = self._resolve_model(config.gemini_model)
        self.model = self.primary_model
        timeout_ms = int(config.request_timeout_sec * 1000)
        self.client = genai.Client(
            api_key=config.gemini_api_key,
            http_options={
                "timeout": timeout_ms,
                "retry_options": {"attempts": 1},
            },
        )
        self._lock = threading.Lock()
        self._call_count = 0
        self._used_models: list[str] = []

    @staticmethod
    def _resolve_model(model_name: str) -> str:
        """Заменить устаревшие модели на актуальную `gemini-4-hydrogen`."""
        normalized = (model_name or "").strip()
        if any(normalized.startswith(prefix) for prefix in DEPRECATED_MODEL_PREFIXES):
            return "gemini-4-hydrogen"
        return normalized or "gemini-4-hydrogen"

    def _candidate_models(self) -> list[str]:
        """Сформировать список моделей, начиная с текущей активной и fallback-цепочки."""
        candidates = [self.model, self.primary_model, *FALLBACK_MODELS]
        deduped: list[str] = []
        for m in candidates:
            if m and m not in deduped:
                deduped.append(m)
        return deduped

    def generate(
        self,
        prompt: str,
        system_instruction: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        """
        Выполнить запрос через `client.interactions.create` с failover по моделям.
        """
        last_error: Exception | None = None
        unavailable_models: set[str] = set()

        for round_idx in range(self.config.max_retries):
            candidates = [m for m in self._candidate_models() if m not in unavailable_models]
            if not candidates:
                break

            for candidate in candidates:
                generation_config: dict[str, Any] = {
                    "temperature": self.config.temperature if temperature is None else temperature,
                    "max_output_tokens": self.config.max_output_tokens if max_tokens is None else max_tokens,
                }
                if self.config.thinking_level and not candidate.startswith("gemma-"):
                    generation_config["thinking_level"] = self.config.thinking_level

                kwargs: dict[str, Any] = {
                    "model": candidate,
                    "input": prompt,
                    "generation_config": generation_config,
                    "store": False,
                    "timeout": self.config.request_timeout_sec,
                }
                if system_instruction:
                    kwargs["system_instruction"] = system_instruction

                use_schema = json_schema is not None and not candidate.startswith("gemma-")
                if use_schema:
                    kwargs["response_format"] = {
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": json_schema,
                    }
                elif json_schema is not None:
                    kwargs["input"] = (
                        f"{prompt}\n\nВерни ответ СТРОГО в виде валидного JSON "
                        f"по следующей JSON Schema (без markdown и пояснений):\n"
                        f"{json.dumps(json_schema, ensure_ascii=False)}"
                    )

                try:
                    interaction = self.client.interactions.create(**kwargs)
                    text = interaction.output_text
                    if not text:
                        raise ValueError(f"Модель {candidate} вернула пустой ответ: status={interaction.status}")

                    with self._lock:
                        self._call_count += 1
                        self.model = candidate
                        if candidate not in self._used_models:
                            self._used_models.append(candidate)

                    return text

                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    err_lower = err_str.lower()

                    if "401" in err_str or "403" in err_str or "api_key_invalid" in err_lower:
                        raise RuntimeError(f"Ошибка авторизации Gemini API: {e}") from e

                    if (
                        "404" in err_str
                        or "limit: 0" in err_lower
                        or "no longer available" in err_lower
                        or "generaterequestsperday" in err_lower
                    ):
                        unavailable_models.add(candidate)
                        continue

                    if "503" in err_str or "429" in err_str or "unavailable" in err_lower or "timed out" in err_lower:
                        continue

                    continue

            if round_idx < self.config.max_retries - 1:
                time.sleep(2.5 * (round_idx + 1) + random.uniform(0.3, 1.2))

        raise RuntimeError(
            f"Не удалось получить ответ от Gemini API после {self.config.max_retries} раундов failover: {last_error}"
        )

    def generate_structured(
        self,
        prompt: str,
        schema_model: Type[T],
        system_instruction: str = "",
        temperature: float | None = None,
    ) -> T:
        """Выполнить запрос со строгим Structured Output и валидацией через Pydantic."""
        raw = self.generate(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            json_schema=schema_model.model_json_schema(),
        )
        cleaned = self._strip_json_fences(raw)
        return schema_model.model_validate_json(cleaned)

    def generate_json(
        self,
        prompt: str,
        system_instruction: str = "",
        temperature: float | None = None,
    ) -> dict | list:
        """Отправить промпт и получить JSON-ответ (без строгой схемы)."""
        raw = self.generate(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
        )
        cleaned = self._strip_json_fences(raw)
        return json.loads(cleaned)

    @staticmethod
    def _strip_json_fences(raw: str) -> str:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
        return text.strip()

    @property
    def call_count(self) -> int:
        with self._lock:
            return self._call_count

    @property
    def active_models_label(self) -> str:
        with self._lock:
            return ", ".join(self._used_models) if self._used_models else self.model
