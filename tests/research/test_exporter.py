"""Offline cross-format and rollback checks for research exports."""

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.collector import BookText, ChapterText, Collector
from research.db import ResearchDB
from research.exporter import export_run
from research.models import BookCandidate
from research.ranking.qidian import RankingSnapshot


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = ResearchDB(self.root / "research.db")
        book = BookCandidate(
            "qidian",
            "sign-new-book",
            "90000001",
            "https://www.qidian.com/book/90000001/",
            "Synthetic Book",
            "Synthetic Author",
            None,
            7,
        )
        body = "A synthetic opening paragraph. " * 20
        chapter = ChapterText(
            "91000001",
            1,
            "Chapter One",
            "https://www.qidian.com/chapter/90000001/91000001",
            body,
            len(body),
            "2026-09-25T00:00:00+00:00",
            hashlib.sha256(body.encode("utf-8")).hexdigest(),
        )

        class Reader:
            def read(self, candidate, chapter_count, cached):
                return BookText(
                    candidate, candidate.title, candidate.author, candidate.category, (chapter,)
                )

        snapshot = RankingSnapshot((book,), datetime(2026, 9, 25, tzinfo=timezone.utc), True)
        self.run_id = Collector(self.db, Reader()).start(snapshot, 1, 1, 1)["run_id"]
        self.output = self.root / "exports"

    def test_jsonl_matches_stored_keys_count_and_hash(self) -> None:
        result = export_run(self.db, self.run_id, "jsonl", self.output)
        self.assertEqual((result["books"], result["chapters"]), (1, 1))
        book = json.loads((self.output / "books.jsonl").read_text(encoding="utf-8"))
        chapter = json.loads((self.output / "chapters.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(book["original_rank"], 7)
        self.assertEqual(book["external_book_id"], chapter["external_book_id"])
        self.assertEqual(chapter["char_count"], len(chapter["text"]))
        self.assertEqual(
            chapter["content_hash"],
            hashlib.sha256(chapter["text"].encode("utf-8")).hexdigest(),
        )

    @unittest.skipUnless(importlib.util.find_spec("pyarrow"), "research extra unavailable")
    def test_parquet_values_match_jsonl(self) -> None:
        import pyarrow.parquet as parquet

        export_run(self.db, self.run_id, "jsonl", self.output)
        export_run(self.db, self.run_id, "parquet", self.output)
        for stem in ("books", "chapters"):
            json_rows = [
                json.loads(line)
                for line in (self.output / f"{stem}.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            parquet_rows = parquet.read_table(self.output / f"{stem}.parquet").to_pylist()
            self.assertEqual(json_rows, parquet_rows)

    def test_failed_second_replacement_restores_both_old_files(self) -> None:
        export_run(self.db, self.run_id, "jsonl", self.output)
        before = {
            stem: (self.output / f"{stem}.jsonl").read_bytes() for stem in ("books", "chapters")
        }
        original_replace = os.replace
        failed = False

        def fail_once(source, target):
            nonlocal failed
            if Path(source).name == "chapters.jsonl" and not failed:
                failed = True
                raise OSError("synthetic second-file failure")
            return original_replace(source, target)

        with patch("research.exporter.os.replace", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "synthetic"):
                export_run(self.db, self.run_id, "jsonl", self.output)
        self.assertEqual(
            {stem: (self.output / f"{stem}.jsonl").read_bytes() for stem in ("books", "chapters")},
            before,
        )


if __name__ == "__main__":
    unittest.main()
