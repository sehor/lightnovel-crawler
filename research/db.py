"""Versioned SQLite storage, isolated from the crawler application's database."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator, Union

DEFAULT_DB_PATH = Path("data/research.db")
SCHEMA_VERSION = 2

_SCHEMA_V1 = (
    """
    CREATE TABLE books (
        id INTEGER PRIMARY KEY,
        platform TEXT NOT NULL CHECK (length(trim(platform)) > 0),
        external_book_id TEXT NOT NULL CHECK (length(trim(external_book_id)) > 0),
        title TEXT NOT NULL CHECK (length(trim(title)) > 0),
        author TEXT NOT NULL CHECK (length(trim(author)) > 0),
        category TEXT,
        book_url TEXT NOT NULL CHECK (length(trim(book_url)) > 0),
        UNIQUE (platform, external_book_id)
    )
    """,
    """
    CREATE TABLE chapters (
        id INTEGER PRIMARY KEY,
        book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        source_chapter_key TEXT NOT NULL CHECK (length(trim(source_chapter_key)) > 0),
        chapter_no INTEGER NOT NULL CHECK (chapter_no > 0),
        title TEXT NOT NULL CHECK (length(trim(title)) > 0),
        source_url TEXT NOT NULL CHECK (length(trim(source_url)) > 0),
        text TEXT NOT NULL,
        char_count INTEGER NOT NULL CHECK (char_count >= 0),
        is_free INTEGER NOT NULL CHECK (is_free IN (0, 1)),
        fetched_at TEXT NOT NULL,
        content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
        UNIQUE (book_id, source_chapter_key),
        UNIQUE (book_id, chapter_no)
    )
    """,
    """
    CREATE TABLE collection_runs (
        run_id TEXT PRIMARY KEY CHECK (length(trim(run_id)) > 0),
        platform TEXT NOT NULL,
        ranking_id TEXT NOT NULL,
        snapshot_at TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        target_books INTEGER NOT NULL CHECK (target_books > 0),
        chapters INTEGER NOT NULL CHECK (chapters > 0),
        max_candidates INTEGER NOT NULL CHECK (max_candidates >= target_books),
        scanned_count INTEGER NOT NULL DEFAULT 0 CHECK (scanned_count >= 0),
        selected_count INTEGER NOT NULL DEFAULT 0 CHECK (selected_count >= 0),
        skipped_count INTEGER NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
        failed_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
        status TEXT NOT NULL CHECK (
            status IN ('running', 'completed', 'partial', 'failed', 'blocked_access')
        )
    )
    """,
    """
    CREATE TABLE run_candidates (
        id INTEGER PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES collection_runs(run_id) ON DELETE CASCADE,
        external_book_id TEXT NOT NULL CHECK (length(trim(external_book_id)) > 0),
        book_url TEXT NOT NULL CHECK (length(trim(book_url)) > 0),
        title TEXT NOT NULL CHECK (length(trim(title)) > 0),
        author TEXT NOT NULL CHECK (length(trim(author)) > 0),
        category TEXT,
        original_rank INTEGER NOT NULL CHECK (original_rank > 0),
        status TEXT NOT NULL DEFAULT 'pending' CHECK (
            status IN ('pending', 'completed', 'skipped', 'failed', 'blocked_access')
        ),
        reason TEXT,
        UNIQUE (run_id, external_book_id),
        UNIQUE (run_id, original_rank)
    )
    """,
    """
    CREATE TABLE ranking_entries (
        id INTEGER PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES collection_runs(run_id) ON DELETE CASCADE,
        book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        original_rank INTEGER NOT NULL CHECK (original_rank > 0),
        UNIQUE (run_id, book_id),
        UNIQUE (run_id, original_rank)
    )
    """,
    "CREATE INDEX ix_chapters_book_no ON chapters(book_id, chapter_no)",
    "CREATE INDEX ix_run_candidates_run_status_rank ON run_candidates(run_id, status, original_rank)",
    "CREATE INDEX ix_ranking_entries_run_rank ON ranking_entries(run_id, original_rank)",
)

_SCHEMA_V2 = ("ALTER TABLE run_candidates ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",)


class ResearchDatabaseError(RuntimeError):
    """Raised when the local research database cannot be initialized safely."""


class ResearchDB:
    """A small database boundary with explicit initialization and transactions."""

    def __init__(self, path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        if str(self.path) == ":memory:":
            raise ValueError("Use a filesystem path for the research database")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        """Create or upgrade the schema without changing the application database."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise ResearchDatabaseError(
                    f"Research database schema {version} is newer than supported "
                    f"version {SCHEMA_VERSION}"
                )
            if version == 0:
                for statement in _SCHEMA_V1:
                    connection.execute(statement)
                version = 1
            if version == 1:
                for statement in _SCHEMA_V2:
                    connection.execute(statement)
                version = 2
            connection.execute(f"PRAGMA user_version = {version}")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a foreign-key-enabled connection and commit or roll it back as a unit."""
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
