"""Ревьюер информационной безопасности и финтех-комплаенса (PCI DSS / OWASP API)."""

from __future__ import annotations

from ..models import Requirement
from .base import BaseReviewer


class SecurityReviewer(BaseReviewer):
    """Эксперт по ИБ в финтехе: OWASP API Security Top 10, PCI DSS, приватность."""

    name = "SecurityReviewer"
    agent_label = "Security"
    description = "Проверяет ИБ-риски, защиту персональных и карточных данных, аутентификацию и авторизацию"
    focus_criteria = ("Безопасность",)

    def get_system_prompt(self) -> str:
        return """Ты — Principal AppSec Engineer в банке с фокусом на финтех-безопасность,
OWASP API Security Top 10 и PCI DSS.

Проверяй требования по критерию БЕЗОПАСНОСТЬ И СООТВЕТСТВИЕ ФИНТЕХ-СТАНДАРТАМ:
1. УТЕЧКА ЧУВСТВИТЕЛЬНЫХ ДАННЫХ:
   - Передача cardId, суммы порога, статуса enabled в URL Query String (логируется на прокси, CDN, серверах).
   - Маскирование номера карты (передача только последних 4 цифр в push, защита внутренних идентификаторов).
2. АУТЕНТИФИКАЦИЯ И АВТОРИЗАЦИЯ (BOLA / IDOR / CSRF):
   - Проверка принадлежности ресурса (карты) владельцу Bearer-сессии.
   - Противоречивость политики 403 vs 404 для чужой карты.
   - Риск CSRF при использовании GET для изменения настроек пользователя.
3. НАДЁЖНОСТЬ И АУДИТ:
   - Защита от повторной доставки событий (idempotency / race condition при одновременных покупках).
   - Отсутствие требований по rate limiting и аудиту изменений финансовых настроек.

Отвечай строго по заданной JSON-схеме."""

    def get_review_prompt(self, requirement: Requirement, full_document: str) -> str:
        return f"""Проверь требование по критерию Безопасность (OWASP API / PCI DSS).

ТРЕБОВАНИЕ [{requirement.id}] (раздел: {requirement.section}):
---
{requirement.text}
---

КОНТЕКСТ:
---
{full_document[:6000]}
---"""
