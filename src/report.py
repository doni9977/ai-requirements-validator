"""Генератор итогового отчёта в форматах Markdown и JSON."""

from __future__ import annotations

from pathlib import Path

from .models import Defect, Severity, ValidationReport


def generate_report(report: ValidationReport) -> str:
    """Сформировать полный Markdown-отчёт по результатам проверки."""
    sections: list[str] = []

    # 1. Паспорт прогона
    sections.append("# Отчёт о статической проверке требований\n")
    sections.append("## 1. Паспорт прогона\n")
    sections.append(f"* **Название проверяемого документа:** `{report.document_name}`")
    sections.append(f"* **Дата и время прогона:** `{report.run_date}`")
    sections.append(f"* **Используемая LLM модель:** `{report.model_name}`")
    sections.append(f"* **Версия агента:** `{report.agent_version}`")
    sections.append(f"* **Время анализа:** `{report.elapsed_seconds:.2f} сек` (вызовов LLM: `{report.llm_calls}`)")
    sections.append("")

    # 2. Нарезка и инвентаризация требований
    sections.append("---\n")
    sections.append("## 2. Нарезка и инвентаризация требований\n")
    sections.append("| ID в отчёте | ID в документе | Раздел документа | Краткая формулировка |")
    sections.append("| :--- | :--- | :--- | :--- |")

    for req in report.requirements:
        source = req.source_id or "—"
        summary = (req.short_summary or req.text[:90]).replace("\n", " ").replace("|", "\\|")
        if len(summary) > 120:
            summary = summary[:117] + "..."
        sec = req.section.replace("|", "\\|") or "—"
        sections.append(f"| `{req.id}` | `{source}` | {sec} | {summary} |")

    sections.append("")

    # 3. Детальная проверка каждого требования
    sections.append("---\n")
    sections.append("## 3. Детальная проверка каждого требования\n")

    for review in report.requirement_reviews:
        req = review.requirement
        title_tail = req.short_summary or req.source_id or "Требование"
        verdict_badge = f" — {review.overall_verdict}" if review.overall_verdict else ""
        sections.append(f"### [{req.id}] {req.section}: {title_tail}{verdict_badge}\n")

        quote_text = req.text[:500] + ("..." if len(req.text) > 500 else "")
        sections.append("**Цитата из документа:**")
        sections.append(f"> {quote_text}\n")

        if review.criteria_results:
            sections.append("**Оценка по критериям качества (ISO/IEC/IEEE 29148):**\n")
            for crit in review.criteria_results:
                icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(crit.status, "⚠️")
                details = f" — {crit.details}" if crit.details else ""
                sections.append(f"* **{crit.criterion}:** {icon} `{crit.status}`{details}")
            sections.append("")

        if review.defects:
            sections.append("**Выявленные дефекты:**\n")
            for defect in review.defects:
                icon = _severity_icon(defect.severity)
                sections.append(
                    f"* {icon} **[{defect.id}] [{defect.severity.value}]** "
                    f"_{defect.criterion}_ (`{defect.source_agent}`): {defect.description}"
                )
                if defect.quote:
                    sections.append(f"  * *Цитата:* «{defect.quote}»")
                if defect.recommendation:
                    sections.append(f"  * ✏️ *Рекомендация:* {defect.recommendation}")
            sections.append("")
        else:
            sections.append("✅ Дефектов не обнаружено.\n")

    # 4. Проверка набора требований в целом
    sections.append("---\n")
    sections.append("## 4. Проверка набора требований в целом\n")

    if report.set_review:
        sr = report.set_review
        sections.append("### 4.1. Системная полнота (Completeness of the Set)\n")
        sections.append(f"{sr.completeness or '—'}\n")

        sections.append("### 4.2. Взаимная непротиворечивость (Internal Consistency)\n")
        sections.append(f"{sr.consistency or '—'}\n")

        sections.append("### 4.3. Прослеживаемость (Traceability)\n")
        sections.append(f"{sr.traceability or '—'}\n")

        if sr.architectural_feasibility:
            sections.append("### 4.4. Архитектурная осуществимость и стандарты (Feasibility & Standards)\n")
            sections.append(f"{sr.architectural_feasibility}\n")

        if sr.defects:
            sections.append("### Системные дефекты набора и структурного анализа\n")
            for defect in sr.defects:
                icon = _severity_icon(defect.severity)
                sections.append(
                    f"* {icon} **[{defect.id}] [{defect.severity.value}]** "
                    f"_{defect.criterion}_ (`{defect.source_agent}`): {defect.description}"
                )
                if defect.quote:
                    sections.append(f"  * *Цитата:* «{defect.quote}»")
                if defect.recommendation:
                    sections.append(f"  * ✏️ *Рекомендация:* {defect.recommendation}")
            sections.append("")

    # 5. Уточняющие вопросы к стейкхолдерам
    sections.append("---\n")
    sections.append("## 5. Уточняющие вопросы к стейкхолдерам\n")

    if report.clarification_questions:
        stakeholders: dict[str, list] = {}
        for q in report.clarification_questions:
            stakeholders.setdefault(q.stakeholder, []).append(q)

        for stakeholder, questions in stakeholders.items():
            sections.append(f"### 📋 {stakeholder}\n")
            for i, q in enumerate(questions, 1):
                icon = _severity_icon(q.priority)
                sections.append(f"{i}. {icon} **[{q.priority.value}]** {q.question}")
                if q.context:
                    sections.append(f"   * *Контекст:* {q.context}")
                if q.suggested_options:
                    sections.append(f"   * *Варианты решения:* {q.suggested_options}")
            sections.append("")
    else:
        sections.append("Уточняющих вопросов не сформировано.\n")

    # 6. Сводная статистика
    sections.append("---\n")
    sections.append("## 6. Сводная статистика проведённого аудита\n")

    sections.append("| Метрика | Значение |")
    sections.append("| :--- | :--- |")
    sections.append(f"| **Всего выделено требований:** | {report.total_requirements} |")
    sections.append(f"| **Требований без дефектов:** | {report.requirements_clean} |")
    sections.append(f"| **Требований с дефектами:** | {report.requirements_with_defects} |")
    sections.append(f"| **Всего дефектов (после дедупликации):** | {report.total_defects} |")
    sections.append(f"| — 🔴 Критичных (CRITICAL / Блокеры): | {report.critical_count} |")
    sections.append(f"| — 🟡 Существенных (MAJOR): | {report.major_count} |")
    sections.append(f"| — 🟢 Замечаний (MINOR): | {report.minor_count} |")
    sections.append(f"| **Находок детерминированного Rule Engine:** | {report.deterministic_findings_count} |")
    sections.append(f"| **Сформировано уточняющих вопросов:** | {len(report.clarification_questions)} |")
    sections.append(f"| **Оценка готовности к разработке:** | **{report.readiness_score}/100** |")
    sections.append("")

    all_defects = _collect_all_defects(report)
    critical = [d for d in all_defects if d.severity == Severity.CRITICAL]
    if critical:
        sections.append("### 🔴 Список критических дефектов (Блокеры разработки):\n")
        for i, d in enumerate(critical, 1):
            sections.append(f"{i}. **[{d.id} / {d.requirement_id}]** {d.description}")
        sections.append("")

    # 7. Итоговый вердикт
    sections.append("---\n")
    sections.append("## 7. Итоговый вердикт и первоочередные рекомендации\n")

    if report.critical_count == 0 and report.readiness_score >= 80:
        sections.append("### ✅ ВЕРДИКТ: ДОКУМЕНТ ДОПУСКАЕТСЯ К РАЗРАБОТКЕ\n")
    elif report.critical_count == 0 and report.readiness_score >= 50:
        sections.append("### ⚠️ ВЕРДИКТ: УСЛОВНО ДОПУСКАЕТСЯ С ОБЯЗАТЕЛЬНОЙ ДОРАБОТКОЙ\n")
    else:
        sections.append("### ⛔ ВЕРДИКТ: РАЗРАБОТКУ И ТЕСТИРОВАНИЕ НАЧИНАТЬ НЕ РЕКОМЕНДУЕТСЯ\n")

    sections.append(f"{report.verdict}\n")

    if report.action_items:
        sections.append("### Что исправить в первую очередь (Action Items):\n")
        for i, item in enumerate(report.action_items, 1):
            sections.append(f"{i}. {item}")
        sections.append("")

    return "\n".join(sections)


def save_report(report: ValidationReport, output_path: str | Path) -> Path:
    """Сформировать и сохранить Markdown-отчёт в файл."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = generate_report(report)
    path.write_text(content, encoding="utf-8")
    return path


def save_report_json(report: ValidationReport, output_path: str | Path) -> Path:
    """Сохранить машинно-читаемый JSON-отчёт."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def _severity_icon(severity: str | Severity) -> str:
    sev = severity.value if isinstance(severity, Severity) else str(severity)
    return {"CRITICAL": "🔴", "MAJOR": "🟡", "MINOR": "🟢"}.get(sev, "⚪")


def _collect_all_defects(report: ValidationReport) -> list[Defect]:
    defects: list[Defect] = []
    for review in report.requirement_reviews:
        defects.extend(review.defects)
    if report.set_review:
        defects.extend(report.set_review.defects)
    return defects
