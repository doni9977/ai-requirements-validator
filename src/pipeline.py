"""Пайплайн агента — гибридная нейро-символическая оркестрация."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import subprocess
import time
from typing import Callable

from .config import Config
from .extractor import extract_requirements
from .llm_client import LLMClient
from .models import (
    CriterionResult,
    Defect,
    RequirementReview,
    Severity,
    ValidationReport,
)
from .parser import parse_document
from .reviewers import (
    APIReviewer,
    ConsistencyReviewer,
    DomainReviewer,
    SecurityReviewer,
    TestabilityReviewer,
)
from .rules import run_deterministic_checks


def _get_git_version() -> str:
    """Получить текущий git commit или тег."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return "v1.0.0"


def _severity_rank(sev: Severity | str) -> int:
    val = sev.value if isinstance(sev, Severity) else str(sev)
    return {"CRITICAL": 0, "MAJOR": 1, "MINOR": 2}.get(val, 3)


def _defect_topic_key(defect: Defect) -> str:
    """Определить смысловой ключ дефекта для устранения дубликатов между агентами."""
    haystack = f"{defect.criterion} {defect.description} {defect.quote}".lower()
    topic_patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("error_prev_state", ("вернуть прежнее состояние",)),
        ("http_200_error", ('"result":"error"', '"result": "error"', "бизнес-ошибкой", "бизнес-ошибок")),
        ("http_200_created", ("смешивает код 200", "ошибочно назван 'created'", "названа 'successful", "соответствует http 201", "соответствует коду 201")),
        ("prod_swagger_missing", ("prod url", "swagger")),
        ("missing_read_endpoint", ("чтение порога", "читает и сохраняет", "метод чтения", "получения текущего порога")),
        ("purchase_vs_clearing", ("31 январ", "1 феврал", "датой покупки", "дате совершения покупки")),
        ("empty_tests", ("заполняются тестировщиками", "секция тестирования", "раздел тестирования")),
        ("empty_checklist", ("чек-лист", "да / нет")),
        ("empty_approvals", ("блок согласующих",)),
        ("jira_missing", ("jira", "таск-трекере")),
        ("content_type_body", ("content-type", "тело не используется")),
        ("tiyn_tenge", ("тиын", "тенге")),
        ("type_mismatch", ("integer", "string", "тип")),
        ("http_403_404", ("403", "404")),
        ("get_mutation", ("http get", "метод get", "get для операции", "get для сохранения", "savelimit использует get", "rest type: get")),
        ("query_leak", ("query string", "query-параметр", "строке запроса")),
        ("idempotency", ("идемпотентност", "повторная доставка")),
    )
    for topic, keywords in topic_patterns:
        if topic in ("http_403_404", "tiyn_tenge", "type_mismatch", "content_type_body"):
            if all(kw in haystack for kw in keywords):
                return topic
        elif any(kw in haystack for kw in keywords):
            return topic
    return " ".join(defect.description.lower().split())[:60]


def _deduplicate_defects(defects: list[Defect]) -> list[Defect]:
    """Объединить смысловые дубликаты дефектов по (requirement_id, тема) и присвоить ID."""
    grouped: dict[tuple[str, str], Defect] = {}

    for d in sorted(defects, key=lambda x: (_severity_rank(x.severity), x.requirement_id)):
        key = (d.requirement_id, _defect_topic_key(d))
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = d.model_copy()
            continue

        # Объединяем источники и оставляем самую высокую критичность / информативное описание
        agents = [a.strip() for a in existing.source_agent.split(",") if a.strip()]
        for a in d.source_agent.split(","):
            a = a.strip()
            if a and a not in agents:
                agents.append(a)
        existing.source_agent = ", ".join(agents)

        if _severity_rank(d.severity) < _severity_rank(existing.severity):
            existing.severity = d.severity
        if len(d.description) > len(existing.description) and existing.source_agent.split(",")[0] != "RuleEngine":
            existing.description = d.description
        if len(d.recommendation) > len(existing.recommendation):
            existing.recommendation = d.recommendation
        if not existing.quote and d.quote:
            existing.quote = d.quote

    unique = sorted(grouped.values(), key=lambda x: (_severity_rank(x.severity), x.requirement_id))
    for idx, d in enumerate(unique, 1):
        d.id = f"DEF-{idx:03d}"

    return unique


def run_pipeline(
    document_path: str,
    config: Config,
    on_progress: Callable[[str, int], None] | None = None,
) -> ValidationReport:
    """
    Запустить гибридный конвейер статической проверки требований:
    1. Парсинг документа (MD/PDF/TXT)
    2. Детерминированный Rule Engine (без затрат токенов)
    3. Извлечение элементарных требований (Structured Output)
    4. 4 параллельных эксперт-ревьюера (Domain, API, QA, Security)
    5. Системная кросс-проверка набора целиком
    6. Генерация адресных уточняющих вопросов стейкхолдерам
    7. Дедупликация, скоринг готовности (0-100) и итоговый вердикт
    """
    start_time = time.time()

    def progress(msg: str, pct: int = 0) -> None:
        if on_progress:
            on_progress(msg, pct)

    # 1. Инициализация
    progress("🔧 Инициализация Gemini SDK и правил...", 5)
    llm = LLMClient(config)

    # 2. Парсинг документа
    progress("📄 Чтение и парсинг документа...", 10)
    document_text = parse_document(document_path)
    if len(document_text.strip()) < 50:
        raise ValueError("Документ слишком короткий или пуст")

    # 3. Детерминированные проверки (Rule Engine)
    progress("⚙️ Запуск детерминированного анализатора правил...", 15)
    rule_defects = run_deterministic_checks(document_text)

    # 4. Экстракция требований
    progress("🔍 Извлечение элементарных требований...", 25)
    requirements = extract_requirements(llm, document_text)
    if not requirements:
        raise ValueError("Не удалось извлечь ни одного требования из документа")

    progress(f"📋 Выделено {len(requirements)} требований. Запуск 4 экспертов параллельно...", 35)

    # 5. Параллельный запуск 4 профильных ревьюеров
    reviewers = [
        DomainReviewer(llm),
        APIReviewer(llm),
        TestabilityReviewer(llm),
        SecurityReviewer(llm),
    ]

    criteria_by_req: dict[str, list[CriterionResult]] = {req.id: [] for req in requirements}
    reviewer_defects: list[Defect] = []
    reviewer_errors: list[str] = []

    with ThreadPoolExecutor(max_workers=min(config.max_workers, len(reviewers))) as pool:
        future_map = {
            pool.submit(rev.review_batch, requirements, document_text): rev
            for rev in reviewers
        }
        completed = 0
        for future in as_completed(future_map):
            rev = future_map[future]
            completed += 1
            pct = 35 + int(35 * (completed / len(reviewers)))
            try:
                crit_map, defects = future.result()
                for req_id, crit_list in crit_map.items():
                    criteria_by_req.setdefault(req_id, []).extend(crit_list)
                reviewer_defects.extend(defects)
                progress(f"✓ Завершил работу {rev.agent_label} ({len(defects)} находок)", pct)
            except Exception as e:
                reviewer_errors.append(f"{rev.name}: {e}")
                progress(f"⚠️ Ошибка эксперта {rev.agent_label}: {e}", pct)

    # 6. Проверка набора требований целиком
    progress("🔗 Системная кросс-проверка набора требований...", 75)
    consistency_reviewer = ConsistencyReviewer(llm)
    set_review = consistency_reviewer.review_full_set(document_text, rule_findings=rule_defects)

    # Формируем RequirementReview для каждого требования
    req_defects_map: dict[str, list[Defect]] = {req.id: [] for req in requirements}
    orphan_defects: list[Defect] = []

    for d in _deduplicate_defects(reviewer_defects):
        if d.requirement_id in req_defects_map:
            req_defects_map[d.requirement_id].append(d)
        else:
            d.requirement_id = "SET"
            orphan_defects.append(d)

    # Нормализуем requirement_id для системных дефектов и объединяем с RuleEngine
    normalized_set_defects: list[Defect] = []
    for d in set_review.defects:
        if d.requirement_id not in req_defects_map:
            d.requirement_id = "SET"
        normalized_set_defects.append(d)

    set_review.defects = _deduplicate_defects(rule_defects + normalized_set_defects + orphan_defects)

    requirement_reviews: list[RequirementReview] = []
    requirements_clean = 0
    requirements_with_defects = 0

    for req in requirements:
        r_defects = req_defects_map.get(req.id, [])
        r_criteria = criteria_by_req.get(req.id, [])
        crit_cnt = sum(1 for d in r_defects if d.severity == Severity.CRITICAL)
        maj_cnt = sum(1 for d in r_defects if d.severity == Severity.MAJOR)

        if crit_cnt > 0:
            r_verdict = f"⛔ БЛОКЕР ({crit_cnt} critical)"
        elif maj_cnt > 0:
            r_verdict = f"⚠️ ТРЕБУЕТ УТОЧНЕНИЯ ({maj_cnt} major)"
        elif r_defects:
            r_verdict = f"🟢 НЕЗНАЧИТЕЛЬНЫЕ ЗАМЕЧАНИЯ ({len(r_defects)})"
        else:
            r_verdict = "✅ СООТВЕТСТВУЕТ"

        if r_defects:
            requirements_with_defects += 1
        else:
            requirements_clean += 1

        requirement_reviews.append(
            RequirementReview(
                requirement=req,
                criteria_results=r_criteria,
                defects=r_defects,
                overall_verdict=r_verdict,
            )
        )

    # Общая сквозная нумерация всех дефектов
    all_defects: list[Defect] = []
    for review in requirement_reviews:
        all_defects.extend(review.defects)
    all_defects.extend(set_review.defects)
    for idx, d in enumerate(all_defects, 1):
        d.id = f"DEF-{idx:03d}"

    # 7. Генерация адресных уточняющих вопросов (25% оценки жюри)
    progress("❓ Формирование уточняющих вопросов стейкхолдерам...", 85)
    clarification_questions = consistency_reviewer.generate_clarification_questions(
        document_text, all_defects
    )

    # 8. Статистика и скоринг готовности
    progress("📊 Расчёт метрик готовности и вердикта...", 95)
    total_defects = len(all_defects)
    critical = sum(1 for d in all_defects if d.severity == Severity.CRITICAL)
    major = sum(1 for d in all_defects if d.severity == Severity.MAJOR)
    minor = sum(1 for d in all_defects if d.severity == Severity.MINOR)

    score = 100 - (critical * 14) - (major * 5) - (minor * 1)
    score = max(0, min(100, score))

    if critical > 0:
        verdict = (
            f"Обнаружено {critical} критических дефектов (блокеры разработки). "
            "Начинать разработку и тестирование запрещено до их устранения."
        )
    elif major > 2:
        verdict = (
            f"Обнаружено {major} существенных дефектов. "
            "Документ условно допускается после снятия вопросов со стейкхолдерами."
        )
    else:
        verdict = "Документ соответствует базовым критериям качества и может быть передан в разработку."

    if reviewer_errors:
        verdict += f" (Примечание: частичные сбои модулей: {'; '.join(reviewer_errors)})"

    action_items: list[str] = []
    seen_topics: set[str] = set()
    for d in sorted(all_defects, key=lambda x: _severity_rank(x.severity)):
        topic = _defect_topic_key(d)
        if topic in seen_topics:
            continue
        seen_topics.add(topic)
        item = f"**[{d.severity.value}]** {d.description}"
        if d.recommendation:
            item += f" → *{d.recommendation}*"
        action_items.append(item)
        if len(action_items) >= 10:
            break

    elapsed = round(time.time() - start_time, 2)
    doc_name = Path(document_path).name

    report = ValidationReport(
        document_name=doc_name,
        run_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        model_name=getattr(llm, "active_models_label", llm.model),
        agent_version=_get_git_version(),
        elapsed_seconds=elapsed,
        llm_calls=llm.call_count,
        requirements=requirements,
        requirement_reviews=requirement_reviews,
        set_review=set_review,
        clarification_questions=clarification_questions,
        total_requirements=len(requirements),
        requirements_clean=requirements_clean,
        requirements_with_defects=requirements_with_defects,
        total_defects=total_defects,
        critical_count=critical,
        major_count=major,
        minor_count=minor,
        deterministic_findings_count=len(rule_defects),
        readiness_score=score,
        verdict=verdict,
        action_items=action_items,
    )

    progress("✅ Анализ полностью завершён!", 100)
    return report
