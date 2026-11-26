"""Конфигурация агента — загрузка переменных окружения и настроек."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_GEMINI_MODEL = "gemini-4-hydrogen"


@dataclass
class Config:
    """Настройки агента, загружаемые из .env или переменных окружения."""

    gemini_api_key: str = ""
    gemini_model: str = DEFAULT_GEMINI_MODEL
    report_language: str = "ru"

    # Внутренние параметры выполнения
    max_retries: int = 2
    temperature: float = 0.15
    max_output_tokens: int = 8192
    max_workers: int = 2
    request_timeout_sec: float = 50.0
    thinking_level: str = "low"

    @classmethod
    def load(cls, env_path: str | Path | None = None) -> "Config":
        """Загрузить конфигурацию из .env файла и переменных окружения."""
        if env_path:
            load_dotenv(env_path)
        else:
            project_root = Path(__file__).resolve().parent.parent
            load_dotenv(project_root / ".env")

        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            report_language=os.getenv("REPORT_LANGUAGE", "ru"),
        )

    def validate(self) -> list[str]:
        """Проверить конфигурацию и вернуть список ошибок."""
        errors = []
        if not self.gemini_api_key or self.gemini_api_key == "your_gemini_api_key_here":
            errors.append(
                "GEMINI_API_KEY не задан. Получите бесплатный ключ: https://aistudio.google.com/"
            )
        return errors
