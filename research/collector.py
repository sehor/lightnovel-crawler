"""Selection, atomic storage, and resume for opening-chapter research."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
import re
import sqlite3
from typing import Dict, List, Mapping, Optional, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from bs4 import BeautifulSoup
from scraper import RenderError

from lncrawl.context import ctx
from lncrawl.core import Novel
from research.db import ResearchDB
from research.models import BookCandidate
from research.ranking.qidian import RankingSnapshot

logger = logging.getLogger(__name__)
_CHAPTER_PATH = re.compile(r"^/chapter/(\d+)/(\d+)/?$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ChapterText:
    source_chapter_key: str
    chapter_no: int
    title: str
    source_url: str
    text: str
    char_count: int
    fetched_at: str
    content_hash: str


@dataclass(frozen=True)
class BookText:
    candidate: BookCandidate
    title: str
    author: str
    category: Optional[str]
    chapters: tuple[ChapterText, ...]


class SkipBook(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AccessBlocked(SkipBook):
    pass


class CandidateReader(Protocol):
    def read(
        self,
        candidate: BookCandidate,
        chapter_count: int,
        cached: Mapping[str, ChapterText],
    ) -> BookText: ...


class QidianBookReader:
    """Use the registered Qidian Source and its shared scraper sessions."""

    def __init__(self) -> None:
        ctx.sources.load(sync_remote=False)
        ctx.sources.ensure_load()

    def read(
        self,
        candidate: BookCandidate,
        chapter_count: int,
        cached: Mapping[str, ChapterText],
    ) -> BookText:
        with ctx.scraper.render_batch():
            return self._read_batch(candidate, chapter_count, cached)

    def _read_batch(
        self,
        candidate: BookCandidate,
        chapter_count: int,
        cached: Mapping[str, ChapterText],
    ) -> BookText:
        url = urlsplit(candidate.book_url)
        if (
            url.scheme != "https"
            or url.hostname != "www.qidian.com"
            or url.path != f"/book/{candidate.external_book_id}/"
        ):
            raise SkipBook("unknown_access")
        crawler = ctx.sources.init_crawler(candidate.book_url)
        try:
            crawler.novel_url = candidate.book_url
            novel = Novel(url=candidate.book_url, volumes=[], chapters=[], tags=[])
            crawler.read_novel(novel)
            crawler.format_novel(novel)
            if len(novel.chapters) < chapter_count:
                raise SkipBook("insufficient_free_chapters")

            chapters: List[ChapterText] = []
            for number, chapter in enumerate(novel.chapters[:chapter_count], start=1):
                chapter_url = urlsplit(chapter.url)
                match = _CHAPTER_PATH.fullmatch(chapter_url.path)
                if (
                    chapter_url.scheme != "https"
                    or chapter_url.hostname != "www.qidian.com"
                    or match is None
                    or match.group(1) != candidate.external_book_id
                    or chapter_url.query
                ):
                    raise SkipBook("unknown_access")
                key = match.group(2)
                prior = cached.get(key)
                if prior is not None and prior.chapter_no == number:
                    chapters.append(prior)
                    continue

                crawler.download_chapter(chapter)
                crawler.format_chapter(chapter)
                text = "\n".join(
                    line.strip()
                    for line in BeautifulSoup(chapter.body or "", "html.parser")
                    .get_text("\n")
                    .splitlines()
                    if line.strip()
                )
                if len(text) < 200:
                    raise SkipBook("invalid_body")
                opening = text[:120]
                if any(
                    prompt in opening
                    for prompt in ("请登录后", "订阅本章", "购买本章", "验证码", "访问被拒绝")
                ):
                    raise AccessBlocked("unknown_access")
                chapters.append(
                    ChapterText(
                        source_chapter_key=key,
                        chapter_no=number,
                        title=chapter.title,
                        source_url=chapter.url,
                        text=text,
                        char_count=len(text),
                        fetched_at=_now(),
                        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    )
                )
            return BookText(
                candidate=candidate,
                title=novel.title,
                author=novel.author or candidate.author,
                category=novel.tags[0] if novel.tags else candidate.category,
                chapters=tuple(chapters),
            )
        finally:
            crawler.close()


class Collector:
    def __init__(self, db: ResearchDB, reader: CandidateReader) -> None:
        self.db = db
        self.reader = reader

    def start(
        self,
        snapshot: RankingSnapshot,
        target_books: int,
        chapter_count: int,
        max_candidates: int,
    ) -> dict:
        if target_books < 1 or chapter_count < 1 or max_candidates < target_books:
            raise ValueError("Invalid collection limits")
        if not snapshot.candidates or len(snapshot.candidates) > max_candidates:
            raise ValueError("Invalid frozen candidate count")
        run_id = uuid4().hex
        started_at = _now()
        with self.db.transaction() as connection:
            connection.execute(
                """INSERT INTO collection_runs
                (run_id, platform, ranking_id, snapshot_at, started_at,
                 target_books, chapters, max_candidates, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running')""",
                (
                    run_id,
                    snapshot.candidates[0].platform,
                    snapshot.candidates[0].ranking_id,
                    snapshot.snapshot_at.isoformat(),
                    started_at,
                    target_books,
                    chapter_count,
                    max_candidates,
                ),
            )
            connection.executemany(
                """INSERT INTO run_candidates
                (run_id, external_book_id, book_url, title, author, category, original_rank)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        item.external_book_id,
                        item.book_url,
                        item.title,
                        item.author,
                        item.category,
                        item.original_rank,
                    )
                    for item in snapshot.candidates
                ],
            )
        return self._process(run_id, retry_failed=False)

    def resume(self, run_id: str) -> dict:
        run = get_status(self.db, run_id)
        if run["status"] == "blocked_access":
            raise ValueError("Run is blocked by site access")
        if run["status"] == "completed":
            return run
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE collection_runs SET status = 'running', finished_at = NULL WHERE run_id = ?",
                (run_id,),
            )
        return self._process(run_id, retry_failed=True)

    def _process(self, run_id: str, retry_failed: bool) -> dict:
        with self.db.transaction() as connection:
            run = connection.execute(
                "SELECT * FROM collection_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            assert run is not None
            rows = connection.execute(
                "SELECT * FROM run_candidates WHERE run_id = ? ORDER BY original_rank",
                (run_id,),
            ).fetchall()

        for row in rows:
            current = get_status(self.db, run_id)
            if current["selected_count"] >= current["target_books"]:
                break
            if row["status"] != "pending" and not (
                retry_failed and row["status"] == "failed" and row["attempts"] < 2
            ):
                continue

            with self.db.transaction() as connection:
                connection.execute(
                    "UPDATE run_candidates SET attempts = attempts + 1 WHERE id = ?",
                    (row["id"],),
                )
            candidate = BookCandidate(
                platform=run["platform"],
                ranking_id=run["ranking_id"],
                external_book_id=row["external_book_id"],
                book_url=row["book_url"],
                title=row["title"],
                author=row["author"],
                category=row["category"],
                original_rank=row["original_rank"],
            )
            try:
                cached = self._cached_chapters(candidate)
                book = self.reader.read(candidate, run["chapters"], cached)
                if len(book.chapters) != run["chapters"]:
                    raise SkipBook("insufficient_free_chapters")
                self._save_book(run_id, book)
            except AccessBlocked as error:
                self._mark_candidate(run_id, row["id"], "blocked_access", error.reason)
                break
            except RenderError:
                self._mark_candidate(run_id, row["id"], "blocked_access", "unknown_access")
                break
            except SkipBook as error:
                self._mark_candidate(run_id, row["id"], "skipped", error.reason)
            except Exception as error:
                logger.warning(
                    "Research candidate %s failed: %s",
                    candidate.external_book_id,
                    type(error).__name__,
                )
                self._mark_candidate(run_id, row["id"], "failed", "fetch_error")

        with self.db.transaction() as connection:
            counts = self._refresh_counts(connection, run_id)
            blocked = connection.execute(
                """SELECT 1 FROM run_candidates
                WHERE run_id = ? AND status = 'blocked_access' LIMIT 1""",
                (run_id,),
            ).fetchone()
            status = (
                "blocked_access"
                if blocked
                else "completed"
                if counts["selected_count"] >= run["target_books"]
                else "partial"
            )
            connection.execute(
                "UPDATE collection_runs SET status = ?, finished_at = ? WHERE run_id = ?",
                (status, _now(), run_id),
            )
        return get_status(self.db, run_id)

    def _cached_chapters(self, candidate: BookCandidate) -> Dict[str, ChapterText]:
        with self.db.transaction() as connection:
            rows = connection.execute(
                """SELECT c.* FROM chapters c JOIN books b ON b.id = c.book_id
                WHERE b.platform = ? AND b.external_book_id = ?""",
                (candidate.platform, candidate.external_book_id),
            ).fetchall()
        return {
            row["source_chapter_key"]: ChapterText(
                source_chapter_key=row["source_chapter_key"],
                chapter_no=row["chapter_no"],
                title=row["title"],
                source_url=row["source_url"],
                text=row["text"],
                char_count=row["char_count"],
                fetched_at=row["fetched_at"],
                content_hash=row["content_hash"],
            )
            for row in rows
            if row["is_free"]
            and row["char_count"] == len(row["text"])
            and row["content_hash"] == hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
        }

    def _save_book(self, run_id: str, book: BookText) -> None:
        with self.db.transaction() as connection:
            connection.execute(
                """INSERT INTO books
                (platform, external_book_id, title, author, category, book_url)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, external_book_id) DO UPDATE SET
                title = excluded.title, author = excluded.author,
                category = excluded.category, book_url = excluded.book_url""",
                (
                    book.candidate.platform,
                    book.candidate.external_book_id,
                    book.title,
                    book.author,
                    book.category,
                    book.candidate.book_url,
                ),
            )
            book_id = connection.execute(
                "SELECT id FROM books WHERE platform = ? AND external_book_id = ?",
                (book.candidate.platform, book.candidate.external_book_id),
            ).fetchone()[0]
            for chapter in book.chapters:
                connection.execute(
                    """INSERT INTO chapters
                    (book_id, source_chapter_key, chapter_no, title, source_url,
                     text, char_count, is_free, fetched_at, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(book_id, source_chapter_key) DO UPDATE SET
                    chapter_no = excluded.chapter_no, title = excluded.title,
                    source_url = excluded.source_url, text = excluded.text,
                    char_count = excluded.char_count, is_free = 1,
                    fetched_at = excluded.fetched_at, content_hash = excluded.content_hash""",
                    (
                        book_id,
                        chapter.source_chapter_key,
                        chapter.chapter_no,
                        chapter.title,
                        chapter.source_url,
                        chapter.text,
                        chapter.char_count,
                        chapter.fetched_at,
                        chapter.content_hash,
                    ),
                )
            connection.execute(
                """INSERT INTO ranking_entries (run_id, book_id, original_rank)
                VALUES (?, ?, ?)""",
                (run_id, book_id, book.candidate.original_rank),
            )
            connection.execute(
                "UPDATE run_candidates SET status = 'completed', reason = NULL WHERE run_id = ? AND external_book_id = ?",
                (run_id, book.candidate.external_book_id),
            )
            self._refresh_counts(connection, run_id)

    def _mark_candidate(self, run_id: str, row_id: int, status: str, reason: str) -> None:
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE run_candidates SET status = ?, reason = ? WHERE id = ?",
                (status, reason, row_id),
            )
            self._refresh_counts(connection, run_id)

    @staticmethod
    def _refresh_counts(connection: sqlite3.Connection, run_id: str) -> dict:
        row = connection.execute(
            """SELECT
                SUM(CASE WHEN status <> 'pending' THEN 1 ELSE 0 END) AS scanned,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS selected,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
                SUM(CASE WHEN status IN ('failed', 'blocked_access') THEN 1 ELSE 0 END) AS failed
            FROM run_candidates WHERE run_id = ?""",
            (run_id,),
        ).fetchone()
        counts = {
            "scanned_count": row["scanned"] or 0,
            "selected_count": row["selected"] or 0,
            "skipped_count": row["skipped"] or 0,
            "failed_count": row["failed"] or 0,
        }
        connection.execute(
            """UPDATE collection_runs SET
            scanned_count = ?, selected_count = ?, skipped_count = ?, failed_count = ?
            WHERE run_id = ?""",
            (*counts.values(), run_id),
        )
        return counts


def get_status(db: ResearchDB, run_id: str) -> dict:
    db.initialize()
    with db.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM collection_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        reasons = connection.execute(
            """SELECT reason, COUNT(*) AS count FROM run_candidates
            WHERE run_id = ? AND reason IS NOT NULL GROUP BY reason""",
            (run_id,),
        ).fetchall()
    result = dict(row)
    result["reasons"] = {item["reason"]: item["count"] for item in reasons}
    return result
