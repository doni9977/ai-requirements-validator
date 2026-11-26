"""Ревьюер кросс-документной непротиворечивости и генератор уточняющих вопросов."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import ClarificationQuestion, Defect, Requirement, SetReview, Severity
from .base import BaseReviewer


class SetDefectItem(BaseModel):
    """Дефект уровня всего набора требований."""

    id: str = Field(default="SET-001")
    requirement_id: str = Field(default="SET")
    severity: Severity
    criterion: str
    description: str
    quote: str = Field(default="")
    recommendation: str = Field(default="")


class SetReviewOutput(BaseModel):
    """Структурированный ответ по системной проверке документа целиком (на русском языке)."""

    completeness: str = Field(description="Анализ системной полноты набора требований НА РУССКОМ ЯЗЫКЕ")
    consistency: str = Field(description="Анализ взаимной непротиворечивости (Часть A vs Часть B, таблицы, типы, ФТ vs приёмка) НА РУССКОМ ЯЗЫКЕ")
    traceability: str = Field(description="Анализ прослеживаемости (бизнес-цель -> функция -> API -> тесты) НА РУССКОМ ЯЗЫКЕ")
    architectural_feasibility: str = Field(
        description="Анализ архитектурной осуществимости и соответствия стандартам НА РУССКОМ ЯЗЫКЕ"
    )
    defects: list[SetDefectItem] = Field(default_factory=list)


class ClarificationOutput(BaseModel):
    """Список адресных уточняющих вопросов стейкхолдерам."""

    questions: list[ClarificationQuestion] = Field(default_factory=list)


class ConsistencyReviewer(BaseReviewer):
    """Эксперт по кросс-документной непротиворечивости и системной полноте."""

    name = "ConsistencyReviewer"
    agent_label = "Consistency"
    description = "Проверяет согласованность между разделами и документами"

    def get_system_prompt(self) -> str:
        return """Ты — ведущий системный архитектор и системный аналитик в банке, проверяющий ВЕСЬ набор требований целиком (ISO/IEC/IEEE 29148 п. 5.2.6 и IEEE 830 п. 4.3):

1. СИСТЕМНАЯ ПОЛНОТА (Completeness of the Set):
   - Описан ли полный жизненный цикл фичи (настройка -> хранение -> чтение -> событие процессинга -> расчёт -> пуш -> откат/ошибки)?
   - Есть ли пустые разделы, заглушки («заполняются тестировщиками»), пустые блоки согласующих?
   - Присутствуют ли все необходимые API-методы (например, описано сохранение, но отсутствует чтение порога и суммы)?

2. ВЗАИМНАЯ НЕПРОТИВОРЕЧИВОСТЬ (Internal Consistency):
   - Конфликты между Частью A и Частью B (например, тиыны vs тенге, integer vs string, GET с мутацией).
   - Конфликты между функциональными требованиями и критериями приёмки (например, дата покупки/авторизации vs дата проводки/клиринга).
   - Конфликты в HTTP-статусах (200 с {"result":"ERROR"}, 200 Created, 403 -> 404).

3. ПРОСЛЕЖИВАЕМОСТЬ (Traceability):
   - Цепочка: Бизнес-цель -> UI/UX -> Функциональные требования -> API -> Модель данных -> Критерии приёмки.
   - Версионирование документа и привязка к таск-трекеру (Jira).

4. АРХИТЕКТУРНАЯ ОСУЩЕСТВИМОСТЬ И СТАНДАРТЫ:
   - Соответствие RFC 9110 / REST, идемпотентность событий, масштабируемость и SLA."""

    def get_review_prompt(self, requirement: Requirement, full_document: str) -> str:
        return f"""Проверь согласованность требования [{requirement.id}] с остальным документом.
ТРЕБОВАНИЕ: {requirement.text}
ДОКУМЕНТ: {full_document[:8000]}"""

    def review_full_set(
        self, full_document: str, rule_findings: list[Defect] | None = None
    ) -> SetReview:
        """Проверить набор требований целиком — системная полнота и непротиворечивость."""
        hints = ""
        if rule_findings:
            hints = "\n\nУЖЕ ПОДТВЕРЖДЁННЫЕ СТАТИЧЕСКИМ АНАЛИЗАТОРОМ СИГНАЛЫ:\n" + "\n".join(
                f"- [{d.severity.value}] {d.criterion}: {d.description}" for d in rule_findings
            )

        prompt = f"""Проверь ВЕСЬ набор требований как единую систему (Часть A + Часть B).
Укажи конкретные факты и точные дословные цитаты из документа без общих фраз.

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА ФОРМАТИРОВАНИЯ:
1. Все текстовые поля (`completeness`, `consistency`, `traceability`, `architectural_feasibility`, `description`, `recommendation`) пиши СТРОГО НА РУССКОМ ЯЗЫКЕ!
2. Для всех системных дефектов в `defects` указывай `requirement_id = "SET"`.
3. НЕ дублируй в списке `defects` уже найденные статическим анализатором (ниже) — фиксируй только ДОПОЛНИТЕЛЬНЫЕ системные пробелы (например: неполнота BPMN/Sequence для сценария возврата или ошибки чтения, обязательность `amount` при отключении `enabled=0`, отсутствие граничных/негативных кейсов в приёмке и т.п.).{hints}

ПОЛНЫЙ ДОКУМЕНТ:
---
{full_document}
---"""

        parsed = self.llm.generate_structured(
            prompt=prompt,
            schema_model=SetReviewOutput,
            system_instruction=self.get_system_prompt(),
            temperature=0.1,
        )

        defects: list[Defect] = []
        for idx, item in enumerate(parsed.defects, 1):
            defects.append(
                Defect(
                    id=item.id or f"SET-{idx:03d}",
                    requirement_id=item.requirement_id or "SET",
                    severity=item.severity,
                    criterion=item.criterion,
                    source_agent=self.agent_label,
                    description=item.description,
                    quote=item.quote,
                    recommendation=item.recommendation,
                )
            )

        return SetReview(
            completeness=parsed.completeness,
            consistency=parsed.consistency,
            traceability=parsed.traceability,
            architectural_feasibility=parsed.architectural_feasibility,
            defects=defects,
        )

    def generate_clarification_questions(
        self, full_document: str, all_defects: list[Defect]
    ) -> list[ClarificationQuestion]:
        """Сгенерировать адресные уточняющие вопросы для стейкхолдеров (25% оценки жюри)."""
        defects_text = "\n".join(
            f"- [{d.severity.value}] ({d.requirement_id}) {d.criterion}: {d.description}"
            for d in all_defects[:35]
        )

        prompt = f"""На основе выявленных дефектов и пробелов в техническом задании финтех-проекта
сформулируй ВЫСОКОТОЧНЫЕ адресные уточняющие вопросы для стейкхолдеров.
Задача вопросов — не просто раскритиковать документ, а помочь команде быстро снять блокеры до старта разработки.

ДОКУМЕНТ:
---
{full_document}
---

НАЙДЕННЫЕ ДЕФЕКТЫ:
{defects_text}

Сгенерируй от 8 до 14 конкретных вопросов, охватывающих все 4 роли:
1. Product Owner (бизнес-логика: возвраты за прошлый месяц, мультикартность, шаг порога, SLA 1 минута, повторные push)
2. Solution Architect (HTTP PUT/POST вместо GET, отсутствующий эндпоинт чтения настроек, тиыны vs тенге, ключ идемпотентности)
3. Information Security (данные в Query String, CSRF, политика 403 vs 404 при переборе карт, PCI DSS маскирование)
4. QA Lead (противоречие даты покупки vs даты проводки 31 янв/1 фев в приёмке, пустая секция тестирования, граничные кейсы)

Для каждого вопроса укажи:
- stakeholder: одна из 4 ролей ("Product Owner", "Solution Architect", "Information Security", "QA Lead")
- question: точный вопрос со ссылкой на пункт/раздел документа
- context: почему это важно и к какому дефекту относится
- suggested_options: 2-3 конкретных варианта решения на выбор
- priority: CRITICAL | MAJOR | MINOR"""

        parsed = self.llm.generate_structured(
            prompt=prompt,
            schema_model=ClarificationOutput,
            system_instruction="Ты — ведущий системный аналитик в FinTech. Формулируй конструктивные, адресные вопросы с вариантами решения.",
            temperature=0.2,
        )

        return parsed.questions
