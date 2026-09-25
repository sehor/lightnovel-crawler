"""Offline regression tests for atomic selection and resumable collection."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from scraper import RenderError

from research.collector import BookText, ChapterText, Collector, SkipBook, get_status
from research.db import ResearchDB
from research.models import BookCandidate
from research.ranking.qidian import RankingSnapshot


def candidate(rank: int) -> BookCandidate:
    book_id = str(90000000 + rank)
    return BookCandidate(
        platform="qidian",
        ranking_id="sign-new-book",
        external_book_id=book_id,
        book_url=f"https://www.qidian.com/book/{book_id}/",
        title=f"Book {rank}",
        author="Example Author",
        category="Fantasy",
        original_rank=rank,
    )


def chapter(number: int) -> ChapterText:
    text = f"Synthetic opening chapter {number}. " * 20
    return ChapterText(
        source_chapter_key=str(91000000 + number),
        chapter_no=number,
        title=f"Chapter {number}",
        source_url=f"https://www.qidian.com/chapter/90000001/{91000000 + number}",
        text=text,
        char_count=len(text),
        fetched_at="2026-09-25T00:00:00+00:00",
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self.fail_once = True

    def read(self, book, chapter_count, cached):
        self.calls.append((book.original_rank, len(cached)))
        if book.original_rank == 1:
            raise SkipBook("insufficient_free_chapters")
        if book.original_rank == 2 and self.fail_once:
            self.fail_once = False
            raise OSError("synthetic network failure")
        chapters = tuple(
            cached.get(str(91000000 + number), chapter(number))
            for number in range(1, chapter_count + 1)
        )
        return BookText(book, book.title, book.author, book.category, chapters)


class CollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = ResearchDB(Path(self.temp.name) / "research.db")
        self.snapshot = RankingSnapshot(
            tuple(candidate(rank) for rank in range(1, 4)),
            datetime(2026, 9, 25, tzinfo=timezone.utc),
            source_exhausted=True,
        )

    def test_skip_failure_resume_and_repeat_keep_complete_books_only(self) -> None:
        reader = FakeReader()
        collector = Collector(self.db, reader)
        first = collector.start(self.snapshot, target_books=2, chapter_count=2, max_candidates=3)
        self.assertEqual(first["status"], "partial")
        self.assertEqual(
            (first["selected_count"], first["skipped_count"], first["failed_count"]),
            (1, 1, 1),
        )
        self.assertEqual(first["reasons"], {"insufficient_free_chapters": 1, "fetch_error": 1})

        resumed = collector.resume(first["run_id"])
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["selected_count"], 2)
        self.assertEqual(resumed["failed_count"], 0)
        self.assertEqual(get_status(self.db, first["run_id"])["status"], "completed")

        repeat = collector.start(self.snapshot, target_books=2, chapter_count=2, max_candidates=3)
        self.assertEqual(repeat["status"], "completed")
        self.assertIn((2, 2), reader.calls)
        with self.db.transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM books").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM chapters").fetchone()[0], 4)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM ranking_entries").fetchone()[0], 4
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM books WHERE external_book_id = '90000001'"
                ).fetchone()[0],
                0,
            )

    def test_chapter_constraint_failure_rolls_back_book_and_chapters(self) -> None:
        class BrokenReader:
            def read(self, book, chapter_count, cached):
                first = chapter(1)
                duplicate_number = chapter(2)
                duplicate_number = ChapterText(
                    duplicate_number.source_chapter_key,
                    1,
                    duplicate_number.title,
                    duplicate_number.source_url,
                    duplicate_number.text,
                    duplicate_number.char_count,
                    duplicate_number.fetched_at,
                    duplicate_number.content_hash,
                )
                return BookText(
                    book, book.title, book.author, book.category, (first, duplicate_number)
                )

        collector = Collector(self.db, BrokenReader())
        snapshot = RankingSnapshot((candidate(1),), self.snapshot.snapshot_at, True)
        result = collector.start(snapshot, target_books=1, chapter_count=2, max_candidates=1)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["failed_count"], 1)
        with self.db.transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM books").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM chapters").fetchone()[0], 0)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM ranking_entries").fetchone()[0], 0
            )

    def test_render_timeout_stops_before_next_candidate(self) -> None:
        class ChallengeReader:
            def __init__(self) -> None:
                self.calls: list[int] = []

            def read(self, book, chapter_count, cached):
                self.calls.append(book.original_rank)
                raise RenderError("catalog never appeared")

        reader = ChallengeReader()
        result = Collector(self.db, reader).start(
            self.snapshot, target_books=1, chapter_count=1, max_candidates=3
        )
        self.assertEqual(result["status"], "blocked_access")
        self.assertEqual(result["scanned_count"], 1)
        self.assertEqual(result["reasons"], {"unknown_access": 1})
        self.assertEqual(reader.calls, [1])
        with self.assertRaises(ValueError):
            Collector(self.db, reader).resume(result["run_id"])


if __name__ == "__main__":
    unittest.main()
