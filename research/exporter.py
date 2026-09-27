"""Verified local JSONL and Parquet exports for one collection run."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Dict, List, Literal, Union

from research.db import ResearchDB

BOOK_FIELDS = (
    "run_id",
    "platform",
    "ranking_id",
    "snapshot_at",
    "original_rank",
    "external_book_id",
    "book_url",
    "title",
    "author",
    "category",
)
CHAPTER_FIELDS = (
    "run_id",
    "platform",
    "external_book_id",
    "source_chapter_key",
    "chapter_no",
    "title",
    "source_url",
    "text",
    "char_count",
    "is_free",
    "fetched_at",
    "content_hash",
)


def _records(db: ResearchDB, run_id: str) -> tuple[List[dict], List[dict]]:
    with db.transaction() as connection:
        run = connection.execute(
            "SELECT * FROM collection_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise KeyError(run_id)
        book_rows = connection.execute(
            """SELECT r.run_id, r.platform, r.ranking_id, r.snapshot_at,
            e.original_rank, b.external_book_id, b.book_url, b.title, b.author, b.category
            FROM ranking_entries e
            JOIN collection_runs r ON r.run_id = e.run_id
            JOIN books b ON b.id = e.book_id
            WHERE e.run_id = ? ORDER BY e.original_rank""",
            (run_id,),
        ).fetchall()
        chapter_rows = connection.execute(
            """SELECT e.run_id, b.platform, b.external_book_id,
            c.source_chapter_key, c.chapter_no, c.title, c.source_url,
            c.text, c.char_count, c.is_free, c.fetched_at, c.content_hash
            FROM ranking_entries e
            JOIN books b ON b.id = e.book_id
            JOIN chapters c ON c.book_id = b.id
            WHERE e.run_id = ? AND c.chapter_no <= ?
            ORDER BY e.original_rank, c.chapter_no""",
            (run_id, run["chapters"]),
        ).fetchall()

    books = [{field: row[field] for field in BOOK_FIELDS} for row in book_rows]
    chapters = []
    for row in chapter_rows:
        item = {field: row[field] for field in CHAPTER_FIELDS}
        item["is_free"] = bool(item["is_free"])
        if (
            item["char_count"] != len(item["text"])
            or item["content_hash"] != hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
            or not item["is_free"]
        ):
            raise ValueError("Stored chapter integrity check failed")
        chapters.append(item)
    if len(chapters) != len(books) * run["chapters"]:
        raise ValueError("Run has incomplete selected books")
    return books, chapters


def _write_jsonl(path: Path, rows: List[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_parquet(path: Path, rows: List[dict], fields: tuple[str, ...]) -> None:
    try:
        import pyarrow as arrow
        import pyarrow.parquet as parquet
    except ImportError as error:
        raise RuntimeError("Parquet export requires: uv sync --extra research") from error

    integer_fields = {"original_rank", "chapter_no", "char_count"}
    schema = arrow.schema(
        [
            (
                name,
                arrow.bool_()
                if name == "is_free"
                else arrow.int64()
                if name in integer_fields
                else arrow.string(),
            )
            for name in fields
        ]
    )
    parquet.write_table(arrow.Table.from_pylist(rows, schema=schema), path)


def export_run(
    db: ResearchDB,
    run_id: str,
    format_name: Literal["jsonl", "parquet"],
    output: Union[str, Path],
) -> Dict[str, object]:
    """Write both files, verify data first, and restore old outputs on failure."""
    if format_name not in ("jsonl", "parquet"):
        raise ValueError("format_name must be jsonl or parquet")
    books, chapters = _records(db, run_id)
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    targets = [directory / f"books.{format_name}", directory / f"chapters.{format_name}"]

    with tempfile.TemporaryDirectory(prefix=".research-export-", dir=directory) as name:
        stage = Path(name)
        staged = [stage / target.name for target in targets]
        writer = _write_jsonl if format_name == "jsonl" else _write_parquet
        writer(staged[0], books) if format_name == "jsonl" else writer(
            staged[0], books, BOOK_FIELDS
        )
        writer(staged[1], chapters) if format_name == "jsonl" else writer(
            staged[1], chapters, CHAPTER_FIELDS
        )

        backups = []
        installed = []
        try:
            for target in targets:
                if target.exists():
                    backup = stage / f"{target.name}.backup"
                    os.replace(target, backup)
                    backups.append((backup, target))
            for source, target in zip(staged, targets):
                os.replace(source, target)
                installed.append(target)
        except Exception:
            for target in installed:
                target.unlink(missing_ok=True)
            for backup, target in backups:
                os.replace(backup, target)
            raise

    return {
        "run_id": run_id,
        "format": format_name,
        "books": len(books),
        "chapters": len(chapters),
        "files": [str(target) for target in targets],
    }
