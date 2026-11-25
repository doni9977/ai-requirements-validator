"""Экстрактор требований — нарезка документа на элементарные требования."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from .models import Requirement

if TYPE_CHECKING:
    from .llm_client import LLMClient


class ExtractedRequirements(BaseModel):
    """Схема структурированного ответа экстрактора."""

    requirements: list[Requirement] = Field(
        description="Полный список элементарных требований из документа"
    )


EXTRACTION_SYSTEM = """Ты — эксперт по анализу технических заданий в сфере финтех.
Твоя задача — извлечь из документа ВСЕ элементарные проверяемые требования и утверждения.

Требование — это отдельное утверждение, которое описывает:
- Цели и архитектуру решения
- Сценарий UI/UX
- BPMN / Sequence-взаимодействие
- Функциональное требование (Ф-1, Ф-2, ...)
- Нефункциональное ограничение (SLA, производительность, безопасность)
- Требование к данным и хранению
- Интеграционное требование (API, эндпоинты, идемпотентность)
- Правила логики метода и особые правила
- Входные параметры и структуру ответов / HTTP-статусов REST API
- Критерий приёмки или тестовый сценарий

ВАЖНО:
- Извлекай требования из ВСЕХ разделов (включая Часть A и Часть B, таблицы параметров, статусы HTTP, критерии приёмки).
- Для каждого требования сохраняй точную цитату из текста в поле `text`.
- Если у требования есть явный идентификатор в документе (например `Ф-1`, `200`, `403`), укажи его в `source_id`. Иначе оставь `""`.
- Присваивай сквозные ID: `REQ-01`, `REQ-02`, ..."""


EXTRACTION_PROMPT = """Извлеки ВСЕ элементарные требования из документа ниже.

ДОКУМЕНТ:
---
{document_text}
---"""


def extract_requirements(llm: "LLMClient", document_text: str) -> list[Requirement]:
    """Извлечь требования из текста документа через LLM со строгой JSON-схемой."""
    prompt = EXTRACTION_PROMPT.format(document_text=document_text)

    parsed = llm.generate_structured(
        prompt=prompt,
        schema_model=ExtractedRequirements,
        system_instruction=EXTRACTION_SYSTEM,
        temperature=0.1,
    )

    requirements: list[Requirement] = []
    for idx, req in enumerate(parsed.requirements, 1):
        if not req.id:
            req.id = f"REQ-{idx:02d}"
        requirements.append(req)

    return requirements
