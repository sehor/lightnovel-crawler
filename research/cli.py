"""Command line entry points for the local research workflow."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import List, Literal, Optional

import typer

from research.db import DEFAULT_DB_PATH, ResearchDB


@dataclass(frozen=True)
class CollectOptions:
    target_books: int = 10
    chapters: int = 5
    max_candidates: int = 50
    db: Path = DEFAULT_DB_PATH
    rankings: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.target_books < 1:
            raise ValueError("--target-books must be at least 1")
        if self.chapters < 1:
            raise ValueError("--chapters must be at least 1")
        if self.max_candidates < 1:
            raise ValueError("--max-candidates must be at least 1")
        if self.max_candidates < self.target_books:
            raise ValueError("--max-candidates must be greater than or equal to --target-books")


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="本地网文开篇研究工具。",
)


def _run_exit_code(status: str) -> int:
    return {"completed": 0, "partial": 2, "blocked_access": 3}.get(status, 1)


@app.command()
def collect(
    target_books: int = typer.Option(10, min=1, help="每个榜单的合格书目标数。"),
    chapters: int = typer.Option(5, min=1, help="每本连续检查的开篇章节数。"),
    max_candidates: int = typer.Option(50, min=1, help="每个榜单最多检查的候选数。"),
    ranking: Optional[List[str]] = typer.Option(
        None,
        "--ranking",
        "-r",
        help="榜单 ID 或起点榜单 URL；可重复指定。省略时运行所有预设榜单。",
    ),
    db: Path = typer.Option(DEFAULT_DB_PATH, help="独立研究 SQLite 文件。"),
) -> None:
    """Collect eligible books from preset or user-selected Qidian rankings."""
    from lncrawl.context import ctx
    from research.collector import Collector, QidianBookReader
    from research.ranking.qidian import (
        QidianRankingProvider,
        RankingAccessError,
        resolve_rankings,
    )

    options = CollectOptions(target_books, chapters, max_candidates, db, tuple(ranking or ()))
    try:
        options.validate()
        selected_rankings = resolve_rankings(options.rankings)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    results = []
    errors = []
    blocked = False
    try:
        collector = Collector(ResearchDB(options.db), QidianBookReader())
        for definition in selected_rankings:
            try:
                scraper = ctx.scraper.open("https://www.qidian.com/", rate_limit=0.1)
                try:
                    provider = QidianRankingProvider(
                        ranking_id=definition.ranking_id,
                        ranking_url=definition.url,
                    )
                    with ctx.scraper.render_batch():
                        snapshot = provider.discover(options.max_candidates, scraper)
                finally:
                    scraper.close()
                result = collector.start(
                    snapshot,
                    target_books=options.target_books,
                    chapter_count=options.chapters,
                    max_candidates=options.max_candidates,
                )
                result["ranking_name"] = definition.name
                result["ranking_url"] = definition.url
                results.append(result)
            except RankingAccessError as error:
                blocked = True
                errors.append(
                    {
                        "ranking_id": definition.ranking_id,
                        "ranking_url": definition.url,
                        "status": "blocked_access",
                        "error": str(error),
                    }
                )
                break
            except Exception as error:
                errors.append(
                    {
                        "ranking_id": definition.ranking_id,
                        "ranking_url": definition.url,
                        "status": "failed",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
    except Exception as error:
        typer.echo(f"collect failed: {type(error).__name__}: {error}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(json.dumps({"runs": results, "errors": errors}, ensure_ascii=False))
    if blocked:
        raise typer.Exit(code=3)
    if errors:
        raise typer.Exit(code=1)
    if any(result["status"] != "completed" for result in results):
        raise typer.Exit(code=2)


@app.command()
def rankings() -> None:
    """List the built-in Qidian ranking presets."""
    from research.ranking.qidian import QIDIAN_RANKINGS

    for ranking in QIDIAN_RANKINGS:
        typer.echo(f"{ranking.ranking_id}\t{ranking.name}\t{ranking.url}")


@app.command()
def resume(
    run_id: str = typer.Option(..., "--run-id", help="要恢复的运行 ID。"),
    db: Path = typer.Option(DEFAULT_DB_PATH, help="独立研究 SQLite 文件。"),
) -> None:
    """Resume a frozen collection run."""
    from research.collector import Collector, QidianBookReader

    try:
        result = Collector(ResearchDB(db), QidianBookReader()).resume(run_id)
    except (KeyError, ValueError) as error:
        typer.echo(f"resume failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps(result, ensure_ascii=False))
    raise typer.Exit(code=_run_exit_code(result["status"]))


@app.command(name="export")
def export_data(
    run_id: str = typer.Option(..., "--run-id", help="要导出的运行 ID。"),
    format_name: Literal["jsonl", "parquet"] = typer.Option(..., "--format", help="导出格式。"),
    output: Path = typer.Option(..., help="输出目录。"),
    db: Path = typer.Option(DEFAULT_DB_PATH, help="独立研究 SQLite 文件。"),
) -> None:
    """Export selected records from one completed run."""
    from research.exporter import export_run

    try:
        result = export_run(ResearchDB(db), run_id, format_name, output)
    except (KeyError, ValueError, RuntimeError, OSError) as error:
        typer.echo(f"export failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps(result, ensure_ascii=False))


@app.command()
def status(
    run_id: str = typer.Option(..., "--run-id", help="要查询的运行 ID。"),
    db: Path = typer.Option(DEFAULT_DB_PATH, help="独立研究 SQLite 文件。"),
) -> None:
    """Show the state and counters for one run."""
    from research.collector import get_status

    try:
        result = get_status(ResearchDB(db), run_id)
    except KeyError as error:
        typer.echo(f"Unknown run_id: {run_id}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps(result, ensure_ascii=False))
