"""Offline schema and transaction checks for the independent research database."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from research.db import SCHEMA_VERSION, ResearchDB


class ResearchDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "research.db"
        self.db = ResearchDB(self.db_path)
        self.db.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _insert_book(connection: sqlite3.Connection, external_id: str = "book-1") -> int:
        cursor = connection.execute(
            """
            INSERT INTO books (platform, external_book_id, title, author, category, book_url)
            VALUES ('qidian', ?, 'Synthetic Book', 'Example Author', NULL,
                    'https://www.qidian.com/book/90000001/')
            """,
            (external_id,),
        )
        return int(cursor.lastrowid)

    def test_schema_is_versioned_and_initialization_is_repeatable(self) -> None:
        self.db.initialize()
        with self.db.transaction() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertTrue(
            {"books", "chapters", "collection_runs", "run_candidates", "ranking_entries"} <= tables
        )

    def test_book_identity_is_unique(self) -> None:
        with self.db.transaction() as connection:
            self._insert_book(connection)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.transaction() as connection:
                self._insert_book(connection)

    def test_foreign_keys_are_enabled_for_every_transaction(self) -> None:
        with self.db.transaction() as connection:
            enabled = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO chapters (
                        book_id, source_chapter_key, chapter_no, title, source_url,
                        text, char_count, is_free, fetched_at, content_hash
                    ) VALUES (999, 'chapter-1', 1, 'Synthetic chapter', 'https://example.invalid/c/1',
                              'synthetic body', 14, 1, '2026-01-01T00:00:00+00:00', ?)
                    """,
                    ("a" * 64,),
                )
        self.assertEqual(enabled, 1)

    def test_failed_chapter_write_rolls_back_book_and_chapter_together(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.transaction() as connection:
                book_id = self._insert_book(connection)
                connection.execute(
                    """
                    INSERT INTO chapters (
                        book_id, source_chapter_key, chapter_no, title, source_url,
                        text, char_count, is_free, fetched_at, content_hash
                    ) VALUES (?, 'chapter-1', 1, 'Synthetic chapter', 'https://example.invalid/c/1',
                              'synthetic body', 14, 1, '2026-01-01T00:00:00+00:00', ?)
                    """,
                    (book_id, "bad-hash"),
                )
        with self.db.transaction() as connection:
            count = int(
                connection.execute(
                    "SELECT count(*) FROM books WHERE external_book_id = 'book-1'"
                ).fetchone()[0]
            )
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
