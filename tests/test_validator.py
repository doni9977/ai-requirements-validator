"""Автоматизированные тесты для AI Requirements Validator."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import Config
from src.extractor import ExtractedRequirements
from src.llm_client import LLMClient
from src.models import ClarificationQuestion, Requirement, Severity
from src.parser import parse_document
from src.pipeline import run_pipeline
from src.report import generate_report, save_report, save_report_json
from src.reviewers.base import BatchCriterionAssessment, BatchDefectItem, BatchReviewOutput
from src.reviewers.consistency import ClarificationOutput, SetDefectItem, SetReviewOutput
from src.rules import run_deterministic_checks


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DOC = PROJECT_ROOT / "docs" / "requirements.md"


class FakeLLMClient:
    """Мок LLM-клиента для детерминированного сквозного тестирования пайплайна."""

    def __init__(self, config: Config):
        self.config = config
        self.model = LLMClient._resolve_model(config.gemini_model)
        self.call_count = 0

    def generate_structured(self, prompt: str, schema_model, system_instruction: str = "", temperature=None):
        self.call_count += 1
        name = schema_model.__name__

        if name == "ExtractedRequirements":
            return ExtractedRequirements(
                requirements=[
                    Requirement(
                        id="REQ-01",
                        source_id="Ф-1",
                        section="Функциональные требования",
                        text="Держатель активной карты KZT задаёт целый порог от 1 000 до 1 000 000 ₸ включительно.",
                        short_summary="Установка порога расходов 1 000–1 000 000 ₸",
                    ),
                    Requirement(
                        id="REQ-02",
                        source_id="Ф-2",
                        section="Функциональные требования",
                        text="Месяц определяется по дате совершения покупки в Алматы. Возврат уменьшает расходы месяца исходной покупки.",
                        short_summary="Расчёт месяца по дате покупки и учёт возвратов",
                    ),
                    Requirement(
                        id="REQ-03",
                        source_id="",
                        section="Часть B. REST API",
                        text="REST type: GET | Request URL: /alerts/saveLimit",
                        short_summary="Сохранение порога через GET /alerts/saveLimit",
                    ),
                ]
            )

        if name == "BatchReviewOutput":
            # Различаем по ролям через system_instruction
            if "API-эксперт" in system_instruction:
                return BatchReviewOutput(
                    assessments=[
                        BatchCriterionAssessment(
                            requirement_id="REQ-03",
                            criterion="Реализуемость",
                            status="FAIL",
                            details="GET используется для мутации настроек",
                        )
                    ],
                    defects=[
                        BatchDefectItem(
                            requirement_id="REQ-03",
                            severity=Severity.CRITICAL,
                            criterion="Реализуемость (RFC 9110)",
                            description="Метод /alerts/saveLimit использует GET для изменения состояния.",
                            quote="REST type: GET | Dev: /alerts/saveLimit",
                            recommendation="Заменить на PUT /alerts/limit с JSON-телом.",
                        )
                    ],
                )
            return BatchReviewOutput(
                assessments=[
                    BatchCriterionAssessment(
                        requirement_id="REQ-01",
                        criterion="Полнота",
                        status="WARN",
                        details="Не указан шаг изменения порога и поведение при нескольких картах",
                    )
                ],
                defects=[
                    BatchDefectItem(
                        requirement_id="REQ-01",
                        severity=Severity.MAJOR,
                        criterion="Полнота",
                        description="Не задан шаг валидации порога и поведение при наличии нескольких карт KZT.",
                        quote="Держатель активной карты KZT задаёт целый порог",
                        recommendation="Уточнить кратность порога и область действия (на карту или счёт).",
                    )
                ],
            )

        if name == "SetReviewOutput":
            return SetReviewOutput(
                completeness="Выявлены незаполненные секции тестирования и согласующих, отсутствует метод чтения порога.",
                consistency="Обнаружено противоречие между датой покупки (Ф-2) и датой проводки (Критерии приёмки), а также тиынами и тенге.",
                traceability="Связь с Jira не указана, версионирование документа отсутствует.",
                architectural_feasibility="Использование GET для saveLimit и возврат ERROR при HTTP 200 нарушают RFC 9110.",
                defects=[
                    SetDefectItem(
                        id="SET-001",
                        requirement_id="SET",
                        severity=Severity.CRITICAL,
                        criterion="Взаимная непротиворечивость",
                        description="Противоречие между Ф-2 (дата совершения покупки) и критерием приёмки (отнесение покупки от 31 января к февралю по дате проводки).",
                        quote="Покупка 31 января в 23:58 -> Провести 1 февраля в 00:03 -> Февральский счётчик вырос",
                        recommendation="Единообразно определить правило расчёта месяца: по дате авторизации или по дате клиринга.",
                    )
                ],
            )

        if name == "ClarificationOutput":
            return ClarificationOutput(
                questions=[
                    ClarificationQuestion(
                        stakeholder="Product Owner",
                        question="Какая дата определяет месяц расхода: дата авторизации покупки или дата финансового клиринга?",
                        context="Ф-2 указывает дату покупки, а таблица приёмки относит покупку 31 января 23:58 к февралю.",
                        suggested_options="1) По дате авторизации (как видит клиент в выписке); 2) По дате клиринга.",
                        priority=Severity.CRITICAL,
                    ),
                    ClarificationQuestion(
                        stakeholder="Solution Architect",
                        question="Какой HTTP-метод и контракт использовать для чтения текущего порога и накопленных расходов?",
                        context="В Части A на экране отображается текущий порог и сумма за месяц, но в Части B описан только saveLimit.",
                        suggested_options="Добавить GET /alerts/limit?cardId=...",
                        priority=Severity.CRITICAL,
                    ),
                ]
            )

        raise AssertionError(f"Неожиданная схема: {name}")


class ValidatorTests(unittest.TestCase):
    def test_parse_sample_document(self) -> None:
        text = parse_document(SAMPLE_DOC)
        self.assertIn("Месячный порог расходов по карте", text)
        self.assertIn("/alerts/saveLimit", text)

        with self.assertRaises(FileNotFoundError):
            parse_document(PROJECT_ROOT / "docs" / "does_not_exist.md")

    def test_parse_pdf_document(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "spec.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((72, 72), "REQ-PDF: Card limit threshold 1000-1000000 KZT")
            doc.save(str(pdf_path))
            doc.close()

            extracted = parse_document(pdf_path)
            self.assertIn("Card limit threshold", extracted)

    def test_deterministic_rules_catch_planted_defects(self) -> None:
        text = parse_document(SAMPLE_DOC)
        findings = run_deterministic_checks(text)
        combined = "\n".join(f"{f.description} {f.quote}".lower() for f in findings)

        self.assertGreaterEqual(len(findings), 12)
        self.assertIn("http get", combined)
        self.assertIn("error", combined)
        self.assertIn("404", combined)
        self.assertIn("тиын", combined)
        self.assertIn("заглушку", combined)
        self.assertIn("тестировщик", combined)
        self.assertIn("чек-лист ревью", combined)
        self.assertIn("amount", combined)
        self.assertIn("enabled", combined)
        self.assertIn("31 января", combined)
        self.assertIn("метод чтения", combined)
        self.assertIn("прежнее состояние", combined)

        # Проверяем, что дедупликация разделяет конфликт 200+ERROR и конфликт возврата прежнего состояния
        from src.pipeline import _deduplicate_defects

        deduped = _deduplicate_defects(findings)
        self.assertEqual(len(deduped), len(findings))

    def test_deprecated_model_auto_upgrade(self) -> None:
        self.assertEqual(LLMClient._resolve_model("gemini-2.5-flash"), "gemini-4-hydrogen")
        self.assertEqual(LLMClient._resolve_model("gemini-1.5-pro"), "gemini-4-hydrogen")
        self.assertEqual(LLMClient._resolve_model("gemini-4-neon"), "gemini-4-neon")

    def test_full_pipeline_mocked_and_report_output(self) -> None:
        cfg = Config(gemini_api_key="test-key", gemini_model="gemini-4-hydrogen")
        with patch("src.pipeline.LLMClient", FakeLLMClient):
            report = run_pipeline(str(SAMPLE_DOC), cfg)

        self.assertEqual(report.total_requirements, 3)
        self.assertEqual(report.llm_calls, 7)  # 1 extract + 4 parallel reviewers + 1 set + 1 clarifier
        self.assertGreater(report.critical_count, 0)
        self.assertLess(report.readiness_score, 50)
        self.assertEqual(len(report.clarification_questions), 2)

        md = generate_report(report)
        for required_header in (
            "## 1. Паспорт прогона",
            "## 2. Нарезка и инвентаризация требований",
            "## 3. Детальная проверка каждого требования",
            "## 4. Проверка набора требований в целом",
            "## 5. Уточняющие вопросы к стейкхолдерам",
            "## 6. Сводная статистика проведённого аудита",
            "## 7. Итоговый вердикт и первоочередные рекомендации",
        ):
            self.assertIn(required_header, md)

        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = save_report(report, Path(tmpdir) / "report.md")
            json_path = save_report_json(report, Path(tmpdir) / "report.json")
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())
            parsed_json = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed_json["document_name"], "requirements.md")


if __name__ == "__main__":
    unittest.main()
