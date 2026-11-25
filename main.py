#!/usr/bin/env python3
"""
AI Requirements Validator — BCC-HUB x MNU FinTech Hackathon

Агент статической проверки технических заданий (ISO/IEC/IEEE 29148:2018).
Гибридный пайплайн: детерминированный Rule Engine + 4 параллельных AI-эксперта.

Запуск:
    python main.py docs/requirements.md output/report.md
    python main.py docs/requirements.md output/report.md --json
    python main.py --help
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="🤖 AI Requirements Validator — Агент проверки качества ТЗ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python main.py docs/requirements.md output/report.md
  python main.py docs/requirements.md output/report.md --json
  python main.py document.pdf output/report.md
  python main.py --env .env.production docs/spec.md result.md
        """,
    )
    parser.add_argument("input", help="Путь к файлу с требованиями (MD, PDF, TXT)")
    parser.add_argument("output", help="Путь к файлу отчёта (MD)")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Дополнительно сохранить структурированный JSON-отчёт рядом с MD-файлом",
    )
    parser.add_argument(
        "--env",
        default=None,
        help="Путь к .env файлу (по умолчанию: .env в корне проекта)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Файл не найден: {input_path}")
        sys.exit(1)

    from src.config import Config

    config = Config.load(args.env)
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"❌ {e}")
        sys.exit(1)

    if HAS_RICH and Console().is_terminal:
        _run_rich(args, config, input_path)
    else:
        _run_plain(args, config, input_path)


def _run_rich(args, config, input_path: Path) -> None:
    """Запуск с Rich-интерфейсом."""
    from src.pipeline import run_pipeline
    from src.report import save_report, save_report_json

    console = Console()
    console.print()
    console.print(
        Panel(
            "[bold cyan]🤖 AI Requirements Validator[/bold cyan]\n"
            "[dim]BCC-HUB x MNU FinTech Hackathon 2026 | ISO/IEC/IEEE 29148[/dim]\n"
            f"[dim]Модель: {config.gemini_model}[/dim]",
            box=box.DOUBLE,
            border_style="cyan",
        )
    )
    console.print(f"  📄 Входной файл: [bold]{input_path}[/bold]")
    console.print(f"  📝 Файл отчёта:  [bold]{args.output}[/bold]")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Запуск анализа...", total=100)

        def on_progress(msg: str, pct: int) -> None:
            progress.update(task, description=msg, completed=pct)

        try:
            report = run_pipeline(
                document_path=str(input_path),
                config=config,
                on_progress=on_progress,
            )
        except Exception as e:
            console.print(f"\n[bold red]❌ Ошибка: {e}[/bold red]")
            sys.exit(1)

    output_path = save_report(report, args.output)
    json_path = None
    if args.json:
        json_path = save_report_json(report, Path(args.output).with_suffix(".json"))

    console.print()

    table = Table(
        title="📊 Сводка проверки",
        box=box.ROUNDED,
        border_style="cyan",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Метрика", style="dim")
    table.add_column("Значение", justify="right")

    table.add_row("Требований извлечено", str(report.total_requirements))
    table.add_row("Находок Rule Engine", str(report.deterministic_findings_count))
    table.add_row("Всего дефектов (уникальных)", str(report.total_defects))
    table.add_row("🔴 Критических (CRITICAL)", f"[bold red]{report.critical_count}[/bold red]")
    table.add_row("🟡 Существенных (MAJOR)", f"[bold yellow]{report.major_count}[/bold yellow]")
    table.add_row("🟢 Замечаний (MINOR)", f"[bold green]{report.minor_count}[/bold green]")
    table.add_row("Уточняющих вопросов", str(len(report.clarification_questions)))

    score = report.readiness_score
    score_style = "[bold green]" if (score >= 80 and report.critical_count == 0) else (
        "[bold yellow]" if (score >= 50 and report.critical_count == 0) else "[bold red]"
    )
    table.add_row("Готовность к разработке", f"{score_style}{score}/100[/]")
    table.add_row("Время анализа", f"{report.elapsed_seconds:.1f} сек")
    table.add_row("Вызовов LLM", str(report.llm_calls))

    console.print(table)
    console.print()

    if report.critical_count == 0 and score >= 80:
        console.print(Panel(f"[bold green]✅ {report.verdict}[/bold green]", border_style="green"))
    elif report.critical_count == 0 and score >= 50:
        console.print(Panel(f"[bold yellow]⚠️ {report.verdict}[/bold yellow]", border_style="yellow"))
    else:
        console.print(Panel(f"[bold red]⛔ {report.verdict}[/bold red]", border_style="red"))

    console.print(f"\n  📄 Отчёт сохранён: [bold green]{output_path}[/bold green]")
    if json_path:
        console.print(f"  📦 JSON-отчёт:     [bold green]{json_path}[/bold green]")
    console.print()


def _run_plain(args, config, input_path: Path) -> None:
    """Запуск без Rich (минимальный вывод)."""
    from src.pipeline import run_pipeline
    from src.report import save_report, save_report_json

    print("🤖 AI Requirements Validator")
    print(f"   Модель: {config.gemini_model}")
    print(f"   Вход:   {input_path}")
    print(f"   Выход:  {args.output}")
    print()

    def on_progress(msg: str, pct: int) -> None:
        print(f"  [{pct:3d}%] {msg}", flush=True)

    try:
        report = run_pipeline(
            document_path=str(input_path),
            config=config,
            on_progress=on_progress,
        )
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)

    output_path = save_report(report, args.output)
    if args.json:
        save_report_json(report, Path(args.output).with_suffix(".json"))

    print(
        f"\n📊 Итог: {report.total_requirements} требований, "
        f"{report.total_defects} дефектов "
        f"(🔴 {report.critical_count} / 🟡 {report.major_count} / 🟢 {report.minor_count})"
    )
    print(f"📈 Готовность: {report.readiness_score}/100")
    print(f"⏱  Время: {report.elapsed_seconds:.1f} сек | LLM вызовов: {report.llm_calls}")
    print(f"\n📄 Отчёт: {output_path}")


if __name__ == "__main__":
    main()
