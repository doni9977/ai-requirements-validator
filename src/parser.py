"""Парсер документов — поддержка Markdown и PDF."""

from __future__ import annotations

from pathlib import Path


def parse_document(filepath: str | Path) -> str:
    """
    Прочитать документ с требованиями и вернуть текст.
    Поддержка: .md, .txt, .pdf
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    suffix = path.suffix.lower()

    if suffix in (".md", ".txt", ".rst"):
        return _parse_text(path)
    elif suffix == ".pdf":
        return _parse_pdf(path)
    else:
        # Пробуем как текст
        return _parse_text(path)


def _parse_text(path: Path) -> str:
    """Прочитать текстовый файл."""
    return path.read_text(encoding="utf-8")


def _parse_pdf(path: Path) -> str:
    """Прочитать PDF через pymupdf4llm (оптимально для LLM-анализа)."""
    try:
        import pymupdf4llm
        return pymupdf4llm.to_markdown(str(path))
    except ImportError:
        # Fallback на pymupdf
        try:
            import pymupdf  # fitz
            doc = pymupdf.open(str(path))
            text_parts = []
            for page in doc:
                text_parts.append(page.get_text())
            doc.close()
            return "\n\n".join(text_parts)
        except ImportError:
            raise ImportError(
                "Для чтения PDF установите pymupdf4llm: pip install pymupdf4llm"
            )
