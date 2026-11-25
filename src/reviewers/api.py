"""Ревьюер REST API, протоколов и согласованности типов данных (RFC 9110)."""

from __future__ import annotations

from ..models import Requirement
from .base import BaseReviewer


class APIReviewer(BaseReviewer):
    """Эксперт по REST API, стандартам HTTP и архитектуре интеграций."""

    name = "APIReviewer"
    agent_label = "API"
    description = "Проверяет REST API на соответствие RFC 7231/9110, типы данных и контракты"
    focus_criteria = ("Реализуемость", "Непротиворечивость")

    def get_system_prompt(self) -> str:
        return """Ты — Solution Architect и API-эксперт с глубоким знанием:
- HTTP стандартов RFC 7231 / RFC 9110 (безопасность и идемпотентность методов, коды ответов)
- REST architectural constraints и OpenAPI/Swagger
- Интеграций банковского процессинга и сервисов уведомлений

Ты проверяешь требования по критериям ISO/IEC/IEEE 29148:2018:

1. РЕАЛИЗУЕМОСТЬ И СТАНДАРТЫ (Feasibility):
   - Корректно ли выбран HTTP-метод? Метод GET НЕ должен мутировать состояние (saveLimit должен быть PUT/POST).
   - Соответствуют ли HTTP-статусы семантике: 200 OK vs 201 Created, возврат {"result":"ERROR"} при HTTP 200, секция 403 с текстом про 404.
   - Указаны ли эндпоинты для всех операций (например, в описании упомянуто «чтение порога», но метода чтения нет).
   - Определён ли ключ идемпотентности для повторной доставки событий процессинга?

2. НЕПРОТИВОРЕЧИВОСТЬ (Consistency):
   - Согласованы ли типы данных (integer в query vs string в JSON response для amount и enabled)?
   - Согласованы ли единицы измерения (тиыны в БД/процессинге vs тенге в UI и API)?
   - Согласованы ли заголовки и тело («Content-Type: application/json» при «Тело не используется»)?

Отвечай строго по заданной JSON-схеме."""

    def get_review_prompt(self, requirement: Requirement, full_document: str) -> str:
        return f"""Проверь требование по критериям Реализуемость и Непротиворечивость (REST/API/Данные).

ТРЕБОВАНИЕ [{requirement.id}] (раздел: {requirement.section}):
---
{requirement.text}
---

КОНТЕКСТ:
---
{full_document[:6000]}
---"""
