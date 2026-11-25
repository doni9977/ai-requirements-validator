"""Интерактивный веб-интерфейс (Streamlit) для демонстрации работы агента."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st

from src.config import Config, DEFAULT_GEMINI_MODEL
from src.pipeline import run_pipeline
from src.report import generate_report


st.set_page_config(
    page_title="AI Requirements Validator | BCC-HUB x MNU",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ AI Requirements Validator")
st.caption("BCC-HUB × MNU FinTech Hackathon 2026 · Статический аудит ТЗ (ISO/IEC/IEEE 29148 & RFC 9110)")

# Боковая панель конфигурации
with st.sidebar:
    st.header("⚙️ Настройки агента")
    env_cfg = Config.load()
    api_key = st.text_input(
        "Gemini API Key",
        value=env_cfg.gemini_api_key if env_cfg.gemini_api_key != "your_gemini_api_key_here" else "",
        type="password",
        help="Бесплатный ключ на https://aistudio.google.com/",
    )
    model_name = st.selectbox(
        "Модель LLM",
        options=["gemini-4-hydrogen", "gemini-4-neon", "gemini-4-carbon", "gemini-3.5-flash-lite"],
        index=0,
    )
    st.divider()
    st.markdown("**Архитектура пайплайна:**")
    st.markdown(
        "1. 📄 Parser (MD / PDF)\n"
        "2. ⚙️ Rule Engine (Deterministic)\n"
        "3. 🔍 Extractor (Structured JSON)\n"
        "4. 🧠 4 Parallel AI Experts:\n"
        "   - Domain / BA\n"
        "   - REST API Architect\n"
        "   - QA Lead\n"
        "   - FinTech Security\n"
        "5. 🔗 Cross-Consistency Checker\n"
        "6. ❓ Clarification Engine"
    )

# Выбор источника документа
col_left, col_right = st.columns([1, 1])
with col_left:
    source_mode = st.radio(
        "Источник проверяемого ТЗ:",
        options=["Использовать кейс хакатона (docs/requirements.md)", "Загрузить файл (MD / PDF / TXT)"],
        horizontal=True,
    )

uploaded_file = None
default_doc = Path(__file__).resolve().parent / "docs" / "requirements.md"

if source_mode.startswith("Загрузить"):
    uploaded_file = st.file_uploader("Загрузите ТЗ", type=["md", "pdf", "txt"])

run_btn = st.button("🚀 Запустить проверку ТЗ", type="primary", use_container_width=True)

if run_btn:
    if not api_key:
        st.error("Укажите Gemini API Key в боковой панели или в файле `.env`.")
        st.stop()

    cfg = Config(gemini_api_key=api_key, gemini_model=model_name or DEFAULT_GEMINI_MODEL)

    target_path: str
    tmp_file_path: Path | None = None

    if source_mode.startswith("Загрузить"):
        if not uploaded_file:
            st.warning("Сначала загрузите файл документа.")
            st.stop()
        suffix = Path(uploaded_file.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_file_path = Path(tmp.name)
        target_path = str(tmp_file_path)
    else:
        if not default_doc.exists():
            st.error(f"Файл {default_doc} не найден.")
            st.stop()
        target_path = str(default_doc)

    progress_bar = st.progress(0, text="Инициализация...")
    try:
        report = run_pipeline(
            target_path,
            cfg,
            on_progress=lambda msg, pct: progress_bar.progress(min(max(pct, 0), 100), text=msg),
        )
        st.session_state["last_report"] = report
    except Exception as exc:
        st.error(f"Ошибка при выполнении проверки: {exc}")
        st.stop()
    finally:
        if tmp_file_path and tmp_file_path.exists():
            os.unlink(tmp_file_path)

# Отображение результатов
report = st.session_state.get("last_report")
if report:
    st.divider()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Готовность ТЗ", f"{report.readiness_score}/100")
    m2.metric("🔴 Critical", report.critical_count)
    m3.metric("🟡 Major", report.major_count)
    m4.metric("🟢 Minor", report.minor_count)
    m5.metric("❓ Вопросов", len(report.clarification_questions))

    if report.critical_count > 0:
        st.error(f"⛔ **Вердикт:** {report.verdict}")
    elif report.major_count > 2:
        st.warning(f"⚠️ **Вердикт:** {report.verdict}")
    else:
        st.success(f"✅ **Вердикт:** {report.verdict}")

    tab1, tab2, tab3, tab4 = st.tabs([
        "❓ Уточняющие вопросы (25%)",
        "🔍 Дефекты по требованиям",
        "🔗 Системный анализ набора",
        "📄 Полный Markdown-отчёт",
    ])

    with tab1:
        st.subheader("Адресные вопросы стейкхолдерам")
        for q in report.clarification_questions:
            with st.expander(f"[{q.priority.value}] {q.stakeholder}: {q.question}"):
                if q.context:
                    st.markdown(f"**Контекст:** {q.context}")
                if q.suggested_options:
                    st.markdown(f"**Варианты решения:** {q.suggested_options}")

    with tab2:
        st.subheader(f"Проверено требований: {report.total_requirements}")
        for rev in report.requirement_reviews:
            r = rev.requirement
            with st.expander(f"{r.id} ({r.section}) — {rev.overall_verdict}"):
                st.markdown(f"> {r.text}")
                if rev.criteria_results:
                    st.markdown("**Критерии ISO 29148:**")
                    for c in rev.criteria_results:
                        st.write(f"- **{c.criterion}**: `{c.status}` — {c.details}")
                if rev.defects:
                    st.markdown("**Дефекты:**")
                    for d in rev.defects:
                        st.markdown(f"- **[{d.severity.value}]** `{d.source_agent}` · {d.description}")
                        if d.recommendation:
                            st.caption(f"Рекомендация: {d.recommendation}")

    with tab3:
        if report.set_review:
            st.markdown("### Системная полнота")
            st.write(report.set_review.completeness)
            st.markdown("### Взаимная непротиворечивость")
            st.write(report.set_review.consistency)
            st.markdown("### Прослеживаемость")
            st.write(report.set_review.traceability)
            if report.set_review.architectural_feasibility:
                st.markdown("### Архитектурная осуществимость")
                st.write(report.set_review.architectural_feasibility)
            st.markdown("### Дефекты уровня набора и Rule Engine")
            for d in report.set_review.defects:
                st.markdown(f"- **[{d.id}] [{d.severity.value}]** (`{d.source_agent}`) {d.description}")

    with tab4:
        md_content = generate_report(report)
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                "⬇️ Скачать отчёт (.md)",
                data=md_content,
                file_name="report.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col_dl2:
            st.download_button(
                "⬇️ Скачать отчёт (.json)",
                data=report.model_dump_json(indent=2),
                file_name="report.json",
                mime="application/json",
                use_container_width=True,
            )
        st.markdown(md_content)
