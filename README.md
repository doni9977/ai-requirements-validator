# 🤖 AI Requirements Validator

> **BCC-HUB x MNU FinTech Hackathon 2026**
>
> Гибридный AI-агент статической проверки технических заданий в сфере FinTech

---

## 📋 Описание

Агент выполняет автоматический статический аудит технических заданий (ТЗ) до начала разработки:
- Поддерживает **Markdown (`.md`)**, **PDF (`.pdf`)** и **TXT (`.txt`)**
- Совмещает **детерминированный Rule Engine** (нулевые галлюцинации по структурным/протокольным нарушениям) и **4 параллельных AI-экспертов**
- Оценивает каждое требование по критериям **ISO/IEC/IEEE 29148:2018 (п. 5.2.5, 5.2.6)** и **IEEE Std 830-1998 (п. 4.3)**
- Проверяет весь набор требований на системную полноту, внутреннюю непротиворечивость и прослеживаемость
- Формирует **адресные уточняющие вопросы** с вариантами решений для `Product Owner`, `Solution Architect`, `Information Security` и `QA Lead`
- Выпускает структурированный отчёт со скорингом готовности (`0–100`) и приоритетными Action Items

### Критерии проверки

| Область | Критерии |
| :--- | :--- |
| **Отдельное требование** | Полнота, Однозначность, Непротиворечивость, Тестируемость, Реализуемость (RFC 9110), Необходимость, Безопасность (OWASP/PCI DSS) |
| **Набор требований целиком** | Системная полнота, Взаимная непротиворечивость (Часть A vs Часть B), Прослеживаемость, Архитектурная осуществимость |

---

## 🚀 Быстрый старт (запуск одной командой)

### 1. Получите бесплатный API-ключ Gemini

Перейдите в [Google AI Studio](https://aistudio.google.com/) → нажмите **Get API Key** → создайте ключ.

### 2. Установите зависимости

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Настройте переменные окружения

```bash
cp .env.example .env
# Откройте .env и вставьте ваш GEMINI_API_KEY
```

### 4. Запустите проверку одной командой

```bash
python main.py docs/requirements.md output/report.md
```

Для сохранения также машинно-читаемого JSON-отчёта:
```bash
python main.py docs/requirements.md output/report.md --json
```

Готовый отчёт будет записан в `output/report.md`.

---

## 🖥 Интерактивное веб-демо (для презентации и визуального аудита)

```bash
pip install -r requirements-ui.txt
streamlit run app.py
```

---

## 🏗 Архитектура агента

```
Входной документ (PDF / MD / TXT)
  │
  ▼
[Document Parser] ──▶ pymupdf4llm (PDF) / UTF-8 reader (MD)
  │
  ├──▶ [Deterministic Rule Engine]  (HTTP GET-мутации, 200+ERROR, тиыны/тенге, заглушки)
  │
  ▼
[Requirements Extractor] ──▶ Structured Output (REQ-01 .. REQ-N с точными цитатами)
  │
  ├──▶ [DomainReviewer]      (ISO 29148: Полнота, Однозначность, Необходимость)
  ├──▶ [APIReviewer]         (RFC 9110, коды статусов, типы и единицы данных)
  ├──▶ [TestabilityReviewer] (Тестируемость, конфликты критериев приёмки)
  └──▶ [SecurityReviewer]    (OWASP API Top 10, PCI DSS, IDOR, Query Leakage)
          │ (4 параллельных потока · Structured JSON Schema)
          ▼
[Cross-Consistency Checker] ──▶ Системная сверка Части A и Части B
          │
          ▼
[Clarification Engine] ──▶ Вопросы + варианты решений для PO / Architect / AppSec / QA
          │
          ▼
[Report Generator] ──▶ Дедупликация, Scorecard (0-100), Markdown & JSON отчёт
```

---

## 🧪 Автотесты

```bash
python -m unittest discover -s tests -v
```

---

## ⚙️ Конфигурация (`.env`)

| Переменная | Описание | По умолчанию |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | API-ключ Google AI Studio | (обязательно) |
| `GEMINI_MODEL` | Модель Gemini (`gemini-4-hydrogen`, `gemini-4-neon`, `gemini-4-carbon`) | `gemini-4-hydrogen` |
| `REPORT_LANGUAGE` | Язык отчёта | `ru` |

---

## 📁 Структура проекта

```
ai-requirements-validator/
├── main.py                     # CLI точка входа (одной командой)
├── app.py                      # Интерактивное веб-демо на Streamlit
├── requirements.txt            # Основные зависимости
├── requirements-ui.txt         # Зависимости для Streamlit UI
├── .env.example                # Шаблон конфигурации (без секретов)
├── docs/
│   └── requirements.md         # Входной документ для проверки
├── src/
│   ├── config.py               # Загрузка .env и валидация конфига
│   ├── llm_client.py           # Клиент google-genai (Interactions API + Structured Output)
│   ├── parser.py               # Парсер MD / PDF / TXT
│   ├── rules.py                # Детерминированный Rule Engine
│   ├── extractor.py            # Экстрактор элементарных требований
│   ├── pipeline.py             # Гибридный параллельный конвейер
│   ├── models.py               # Pydantic-модели отчёта
│   ├── report.py               # Генератор отчёта (MD + JSON)
│   └── reviewers/
│       ├── base.py             # Базовый батч-ревьюер
│       ├── domain.py           # Бизнес-логика и полнота
│       ├── api.py              # REST API и протоколы
│       ├── testability.py      # QA и тестируемость
│       ├── security.py         # ИБ, OWASP API, PCI DSS
│       └── consistency.py      # Кросс-консистентность и уточняющие вопросы
├── tests/
│   └── test_validator.py       # Юнит и интеграционные тесты пайплайна
└── output/                     # Директория для сгенерированных отчётов
```
