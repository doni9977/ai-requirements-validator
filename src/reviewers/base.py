"""Базовый класс ревьюера требований с поддержкой батч-проверки."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..models import CriterionResult, Defect, Requirement, Severity

if TYPE_CHECKING:
    from ..llm_client import LLMClient


class BatchDefectItem(BaseModel):
    """Дефект, найденный в рамках батч-анализа требований."""

    requirement_id: str = Field(description="ID требования из списка (REQ-01, ...)")
    severity: Severity = Field(description="CRITICAL | MAJOR | MINOR")
    criterion: str = Field(description="Нарушенный критерий ISO 29148 или стандарта")
    description: str = Field(description="Конкретное описание дефекта с привязкой к тексту")
    quote: str = Field(default="", description="Точная цитата из документа")
    recommendation: str = Field(default="", description="Конкретная рекомендация по исправлению")


class BatchCriterionAssessment(BaseModel):
    """Оценка конкретного критерия качества для одного требования."""

    requirement_id: str = Field(description="ID требования (REQ-01, ...)")
    criterion: str = Field(description="Название критерия (Полнота, Однозначность, ...)")
    status: str = Field(description="PASS | WARN | FAIL")
    details: str = Field(default="", description="Краткое обоснование")


class BatchReviewOutput(BaseModel):
    """Структурированный ответ эксперта-ревьюера по пакету требований."""

    assessments: list[BatchCriterionAssessment] = Field(
        default_factory=list,
        description="Оценка профильных критериев по требованиям",
    )
    defects: list[BatchDefectItem] = Field(
        default_factory=list,
        description="Найденные дефекты с точной привязкой к requirement_id и цитатам",
    )


class BaseReviewer(ABC):
    """Базовый эксперт-ревьюер (поддерживает пакетный и одиночный режим)."""

    name: str = "BaseReviewer"
    agent_label: str = "Expert"
    description: str = ""
    focus_criteria: tuple[str, ...] = ()

    def __init__(self, llm: "LLMClient"):
        self.llm = llm

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Системный промпт для эксперта."""
        ...

    @abstractmethod
    def get_review_prompt(self, requirement: Requirement, full_document: str) -> str:
        """Промпт для проверки одного требования."""
        ...

    def get_batch_prompt(self, requirements: list[Requirement], full_document: str) -> str:
        """Промпт для пакетного анализа всех требований за один вызов."""
        req_blocks = []
        for req in requirements:
            src = f" [{req.source_id}]" if req.source_id else ""
            req_blocks.append(
                f"### {req.id}{src} | Раздел: {req.section}\n"
                f"Текст: {req.text}"
            )
        reqs_formatted = "\n\n".join(req_blocks)
        criteria_list = ", ".join(self.focus_criteria) if self.focus_criteria else "профильные критерии"

        return f"""Проведи аудит ВСЕХ перечисленных требований по своей специализации ({criteria_list}).

ПРАВИЛА:
1. Никаких общих фраз — каждый дефект должен ссылаться на конкретный `requirement_id` и ДОСЛОВНУЮ цитату (`quote`) без искажения чисел и имён.
2. Для КАЖДОГО требования оцени свои профильные критерии ({criteria_list}) в `assessments` со статусом PASS / WARN / FAIL.
3. Если в требовании всё корректно по твоим критериям — дефект не создавай, поставь PASS.
4. Не дублируй очевидную воду — фиксируй только реальные инженерные, логические и тестовые проблемы (включая противоречия между разными пунктами документа).
5. Пиши все поля (`details`, `description`, `recommendation`) СТРОГО НА РУССКОМ ЯЗЫКЕ.

СПИСОК ИЗВЛЕЧЁННЫХ ТРЕБОВАНИЙ:
{reqs_formatted}

ПОЛНЫЙ ДОКУМЕНТ (для проверки контекста и связей):
---
{full_document}
---"""

    def review_batch(
        self, requirements: list[Requirement], full_document: str
    ) -> tuple[dict[str, list[CriterionResult]], list[Defect]]:
        """Проверить пакет требований за один структурированный вызов LLM."""
        if not requirements:
            return {}, []

        prompt = self.get_batch_prompt(requirements, full_document)
        parsed = self.llm.generate_structured(
            prompt=prompt,
            schema_model=BatchReviewOutput,
            system_instruction=self.get_system_prompt(),
            temperature=0.1,
        )

        criteria_map: dict[str, list[CriterionResult]] = {r.id: [] for r in requirements}
        for item in parsed.assessments:
            if item.requirement_id in criteria_map:
                norm_status = item.status.upper().strip()
                if norm_status not in ("PASS", "WARN", "FAIL"):
                    norm_status = "WARN"
                criteria_map[item.requirement_id].append(
                    CriterionResult(
                        criterion=item.criterion,
                        status=norm_status,
                        passed=(norm_status == "PASS"),
                        details=item.details,
                    )
                )

        defects: list[Defect] = []
        for idx, item in enumerate(parsed.defects, 1):
            defects.append(
                Defect(
                    id=f"DEF-{self.agent_label[:3].upper()}-{idx:03d}",
                    requirement_id=item.requirement_id,
                    severity=item.severity,
                    criterion=item.criterion,
                    source_agent=self.agent_label,
                    description=item.description,
                    quote=item.quote,
                    recommendation=item.recommendation,
                )
            )

        return criteria_map, defects

    def review_requirement(
        self, requirement: Requirement, full_document: str
    ) -> list[Defect]:
        """Проверить одно требование (резервный точечный режим)."""
        _, defects = self.review_batch([requirement], full_document)
        return defects
