"""Pydantic-модели данных для агента проверки требований."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class CriterionResult(BaseModel):
    """Результат проверки одного критерия качества для требования."""

    criterion: str = Field(description="Название критерия (Полнота, Однозначность, ...)")
    status: str = Field(default="PASS", description="PASS | WARN | FAIL")
    passed: bool = Field(default=True, description="Пройден ли критерий")
    details: str = Field(default="", description="Краткое пояснение оценки со ссылкой на текст")


class Defect(BaseModel):
    """Один выявленный дефект в требовании или наборе."""

    id: str = Field(description="ID дефекта (DEF-001)")
    requirement_id: str = Field(description="ID требования (REQ-01) или SET")
    severity: Severity = Field(description="Уровень критичности: CRITICAL | MAJOR | MINOR")
    criterion: str = Field(description="Нарушенный критерий ISO/IEC/IEEE 29148 или стандарта")
    source_agent: str = Field(default="LLM", description="Источник находки (RuleEngine, Domain, API, QA, Security)")
    description: str = Field(description="Чёткое описание дефекта с привязкой к документу")
    quote: str = Field(default="", description="Точная цитата из документа")
    recommendation: str = Field(default="", description="Конкретная рекомендация по исправлению")


class Requirement(BaseModel):
    """Одно элементарное требование, извлечённое из документа."""

    id: str = Field(description="ID в отчёте (REQ-01, REQ-02, ...)")
    source_id: str = Field(default="", description="ID в документе (Ф-1, Ф-2, ...)")
    section: str = Field(default="", description="Раздел документа")
    text: str = Field(description="Полный текст / точная цитата требования")
    short_summary: str = Field(default="", description="Краткая формулировка")


class RequirementReview(BaseModel):
    """Полный результат ревью одного требования."""

    requirement: Requirement
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    defects: list[Defect] = Field(default_factory=list)
    overall_verdict: str = Field(default="", description="Общий вердикт по требованию")


class SetReview(BaseModel):
    """Результат проверки набора требований в целом."""

    completeness: str = Field(default="", description="Системная полнота")
    consistency: str = Field(default="", description="Взаимная непротиворечивость")
    traceability: str = Field(default="", description="Прослеживаемость")
    architectural_feasibility: str = Field(
        default="", description="Архитектурная осуществимость и соответствие стандартам"
    )
    defects: list[Defect] = Field(default_factory=list)


class ClarificationQuestion(BaseModel):
    """Уточняющий вопрос к стейкхолдеру."""

    stakeholder: str = Field(description="Роль (Product Owner, Solution Architect, QA Lead, Information Security)")
    question: str = Field(description="Конкретная формулировка вопроса")
    context: str = Field(default="", description="Ссылка на раздел/цитату и причину вопроса")
    suggested_options: str = Field(default="", description="Варианты решения для выбора стейкхолдером")
    priority: Severity = Field(default=Severity.MAJOR, description="Приоритет вопроса")


class ValidationReport(BaseModel):
    """Полный отчёт о статической проверке требований."""

    # Паспорт прогона
    document_name: str = ""
    run_date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    model_name: str = ""
    agent_version: str = ""
    elapsed_seconds: float = 0.0
    llm_calls: int = 0

    # Нарезка
    requirements: list[Requirement] = Field(default_factory=list)

    # Детальная проверка
    requirement_reviews: list[RequirementReview] = Field(default_factory=list)

    # Проверка набора
    set_review: Optional[SetReview] = None

    # Уточняющие вопросы
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list)

    # Сводка
    total_requirements: int = 0
    requirements_clean: int = 0
    requirements_with_defects: int = 0
    total_defects: int = 0
    critical_count: int = 0
    major_count: int = 0
    minor_count: int = 0
    deterministic_findings_count: int = 0

    # Вердикт
    readiness_score: int = Field(default=0, description="Баллы готовности 0-100")
    verdict: str = ""
    action_items: list[str] = Field(default_factory=list)
