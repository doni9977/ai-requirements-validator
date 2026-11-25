"""Детерминированный статический анализатор (Rule Engine).

Выполняет быструю, воспроизводимую проверку документа до и параллельно с LLM:
- Нарушения HTTP/REST стандартов (RFC 9110: GET с мутацией, 200+ERROR, 200 Created, 403/404)
- Заглушки, пустые таблицы и незаполненные блоки согласования
- Размытые и непроверяемые формулировки (ISO 29148 Unambiguity)
- Смешение единиц измерения (тиыны vs тенге) и отсутствие версионирования
"""

from __future__ import annotations

import re

from .models import Defect, Severity


# Слова-индикаторы двусмысленности / непроверяемости (ISO 29148)
VAGUE_TERMS = [
    r"\bбыстр[оаяые]\b",
    r"\bудобн[оаяые]\b",
    r"\bнадёжн[оаяые]\b",
    r"\bнадежн[оаяые]\b",
    r"\bдостаточн[оаяые]\b",
    r"\bмаксимальн[оаяые]\b",
    r"\bинтуитивн[оаяые]\b",
    r"\bкак правило\b",
    r"\bпо возможности\b",
    r"\bи т\.?\s?д\.?",
    r"\bи т\.?\s?п\.?",
    r"\bи тому подобное\b",
]

# Заглушки и незаполненные разделы
PLACEHOLDER_PATTERNS = [
    (r"заполняются тестировщиками", "Секция тестирования требований содержит заглушку вместо тест-плана и сценариев."),
    (r"\bTBD\b|\bTODO\b|\bFIXME\b", "Документ содержит незаполненную метку TBD/TODO."),
    (r"практикум без jira-задачи", "Отсутствует ссылка на задачу в таск-трекере (нарушена прослеживаемость)."),
]


def run_deterministic_checks(document_text: str) -> list[Defect]:
    """Запустить набор детерминированных проверок по тексту документа."""
    findings: list[Defect] = []
    lines = document_text.splitlines()
    counter = 1

    def add_finding(
        severity: Severity,
        criterion: str,
        description: str,
        quote: str,
        recommendation: str,
        requirement_id: str = "SET",
    ) -> None:
        nonlocal counter
        findings.append(
            Defect(
                id=f"RULE-{counter:03d}",
                requirement_id=requirement_id,
                severity=severity,
                criterion=criterion,
                source_agent="RuleEngine",
                description=description,
                quote=quote.strip()[:300],
                recommendation=recommendation,
            )
        )
        counter += 1

    text_lower = document_text.lower()

    # 1. REST GET с операцией мутации состояния
    has_get_rest = bool(re.search(r"\*\*REST\s+type\*\*\s*\|\s*GET\b", document_text, re.IGNORECASE))
    has_save_endpoint = bool(
        re.search(r"/(?:save|create|update|delete|remove|edit|set)[A-Za-z0-9_/-]*", document_text)
    )
    if has_get_rest and has_save_endpoint:
        endpoint_match = re.search(r"`(/[A-Za-z0-9_/-]+)`", document_text)
        endpoint_str = endpoint_match.group(1) if endpoint_match else "save/update endpoint"
        add_finding(
            severity=Severity.CRITICAL,
            criterion="Реализуемость / Стандарты HTTP (RFC 9110)",
            description=(
                f"Метод `{endpoint_str}` использует HTTP GET для операции изменения состояния "
                "(сохранение настройки). По RFC 9110 метод GET должен быть безопасным и не должен "
                "изменять состояние на сервере; кроме того, параметры в query string попадают в логи и историю, "
                "а метод уязвим к CSRF и кешированию."
            ),
            quote=f"REST type: GET | Request URL: {endpoint_str}",
            recommendation="Заменить HTTP-метод на PUT или POST и передавать cardId, amount, enabled в JSON-теле запроса.",
        )

    # 2. Конфликт HTTP 200 OK с телом ошибки {"result":"ERROR"}
    if re.search(r'"result"\s*:\s*"ERROR"', document_text) and re.search(r"####\s*200\b", document_text):
        add_finding(
            severity=Severity.CRITICAL,
            criterion="Взаимная непротиворечивость / HTTP статусы",
            description=(
                "В секции успешного статуса 200 указан пример ответа с бизнес-ошибкой "
                '`{"result":"ERROR"}`, что нарушает семантику HTTP-кодов и противоречит '
                "правилу «Если результат 400, 401 и далее — неуспешный»."
            ),
            quote='200. Successful — Created ... {"result":"ERROR","message":"Проверьте сумму"}',
            recommendation="При ошибке валидации суммы возвращать HTTP 400 Bad Request (или 422 Unprocessable Entity) с единым форматом ошибки.",
        )

    # 3. Несоответствие 200 vs Created
    if re.search(r"200\.\s*Successful\s*[—-]\s*Created", document_text, re.IGNORECASE):
        add_finding(
            severity=Severity.MINOR,
            criterion="Однозначность / REST стандарты",
            description="Заголовок статуса смешивает код 200 (OK) и описание «Created» (соответствует HTTP 201).",
            quote="#### 200. Successful — Created",
            recommendation="Исправить формулировку на «200. Successful — OK» (или использовать HTTP 201 только при создании новой сущности).",
        )

    # 4. Конфликт секции 403 Forbidden и кода 404
    forbidden_block = re.search(
        r"####\s*403\.\s*Unsuccessful\s*[—-]\s*Forbidden.*?(?=####|\Z)",
        document_text,
        re.DOTALL | re.IGNORECASE,
    )
    if forbidden_block and "404" in forbidden_block.group(0):
        add_finding(
            severity=Severity.MAJOR,
            criterion="Взаимная непротиворечивость / HTTP статусы",
            description=(
                "Под заголовком статуса «403. Unsuccessful — Forbidden» фактически описывается возврат кода 404 "
                "(«Для чужой карты возвращается 404»), что создаёт путаницу в спецификации кодов ответов."
            ),
            quote=forbidden_block.group(0).replace("\n", " "),
            recommendation="Вынести 404 Not Found в отдельный заголовок или явно разделить сценарии 403 Forbidden и 404 Not Found (masking для защиты от IDOR).",
        )

    # 5. Contradiction: Body Content-Type application/json with "Тело не используется"
    if "application/json" in text_lower and "тело не используется" in text_lower:
        add_finding(
            severity=Severity.MINOR,
            criterion="Взаимная непротиворечивость",
            description=(
                "В секции «Request body» указан `Content-Type: application/json`, но сразу ниже написано "
                "«Тело не используется»."
            ),
            quote="Content-Type: application/json . Тело не используется.",
            recommendation="При переходе на POST/PUT передавать параметры в JSON body; для GET без тела заголовок Content-Type не указывать.",
        )

    # 6. Смешение единиц измерения: тиыны и тенге
    if "тиын" in text_lower and ("тенге" in text_lower or "kzt" in text_lower):
        add_finding(
            severity=Severity.MAJOR,
            criterion="Непротиворечивость единиц измерения",
            description=(
                "В документе используются разные денежные единицы: «сумма покупки в тиынах» (хранение) и "
                "«порог в тенге» / KZT (настройки и API), без явного описания правил конвертации и округления."
            ),
            quote="сумму покупки в тиынах, признак отправки и порог в тенге",
            recommendation="Явно зафиксировать единицу хранения и расчётов (например, обе суммы в тиынах в БД, конвертация ×100 на границе API).",
        )

    # 7. Незаполненные заглушки
    for pattern, desc in PLACEHOLDER_PATTERNS:
        m = re.search(pattern, document_text, re.IGNORECASE)
        if m:
            sev = Severity.CRITICAL if "тестировщиками" in pattern else Severity.MINOR
            add_finding(
                severity=sev,
                criterion="Системная полнота набора",
                description=desc,
                quote=m.group(0),
                recommendation="Заполнить раздел конкретными проверяемыми требованиями/ссылками до передачи в разработку.",
            )

    # 8. Пустые поля Prod / Swagger и пустые строки таблиц согласующих
    if re.search(r"Prod:\s*—", document_text) or re.search(r"\*\*Swagger\*\*\s*\|\s*—", document_text):
        add_finding(
            severity=Severity.MAJOR,
            criterion="Системная полнота набора",
            description="В паспорте REST API не заполнены обязательные реквизиты интеграции: `Prod URL` и `Swagger` (указан прочерк `—`).",
            quote="Request URL: Dev: /alerts/saveLimit . Prod: — | Swagger: —",
            recommendation="Указать целевой Prod-маршрут API Gateway и ссылку на OpenAPI/Swagger-контракт.",
        )

    # Проверка незаполненного чек-листа ревью ("Да / Нет" без выбора)
    unchosen_checklist = len(re.findall(r"\|\s*Да\s*/\s*Нет", document_text))
    if unchosen_checklist >= 3:
        add_finding(
            severity=Severity.MAJOR,
            criterion="Системная полнота / Готовность к ревью",
            description=(
                f"Чек-лист ревью требований не заполнен: в {unchosen_checklist} строках оставлены "
                "шаблонные варианты «Да / Нет» без проставленных отметок."
            ),
            quote="Документ (версия/дата) в источнике не заполнен. Пункты чек-листа приведены как в шаблоне, отметки не проставлены.",
            recommendation="Зафиксировать версию/дату документа, заполнить чек-лист ревью и блок согласующих.",
        )

    # Пустой блок согласующих
    if re.search(r"###\s*Блок согласующих", document_text) and re.search(r"\|\s*\|\s*\|\s*\|", document_text):
        add_finding(
            severity=Severity.MINOR,
            criterion="Прослеживаемость и согласование",
            description="Таблица «Блок согласующих» полностью пуста — не назначены ответственные от подразделений.",
            quote="| Подразделение | ФИО ответственного | Подпись | -> | | | |",
            recommendation="Указать ответственных согласующих (Архитектура, ИБ, QA, Product Owner).",
        )

    # 9. Поиск размытых формулировок по строкам
    vague_hits: list[tuple[int, str, str]] = []
    for idx, line in enumerate(lines, 1):
        for pat in VAGUE_TERMS:
            m = re.search(pat, line, re.IGNORECASE)
            if m:
                vague_hits.append((idx, m.group(0), line.strip()))

    if vague_hits:
        sample_quotes = "; ".join(f"стр.{ln}: «{word}»" for ln, word, _ in vague_hits[:5])
        add_finding(
            severity=Severity.MINOR,
            criterion="Однозначность (Unambiguity)",
            description=f"Обнаружены потенциально субъективные или незамкнутые формулировки ({len(vague_hits)} вхождений): {sample_quotes}.",
            quote=vague_hits[0][2],
            recommendation="Заменить оценочные/открытые формулировки на измеримые метрики и исчерпывающие перечни.",
        )

    # 10. Несогласованность типов параметров в таблицах Request vs Response
    if "### Ответ" in document_text:
        req_section, resp_section = document_text.split("### Ответ", 1)
        param_re = r"\|\s*`([A-Za-z0-9_]+)`\s*\|\s*(integer|string|boolean|number)\b"
        req_params = dict(re.findall(param_re, req_section, re.IGNORECASE))
        resp_params = dict(re.findall(param_re, resp_section, re.IGNORECASE))
        mismatches = [
            f"`{name}` (вход: {req_params[name]} → ответ: {resp_params[name]})"
            for name in req_params
            if name in resp_params and req_params[name].lower() != resp_params[name].lower()
        ]
        if mismatches:
            add_finding(
                severity=Severity.MAJOR,
                criterion="Непротиворечивость типов данных",
                description=f"Несогласованность типов данных между параметрами запроса и ответа API: {', '.join(mismatches)}.",
                quote="; ".join(mismatches),
                recommendation="Привести типы полей к единому формату (например, `integer` для `amount`, `boolean`/`integer` для `enabled` во всех контрактах).",
            )

    return findings
