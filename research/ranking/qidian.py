"""Qidian signed-new-book ranking discovery and snapshot logic."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Iterable, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from scraper import Scraper

from research.models import BookCandidate

QIDIAN_RANKING_ID = "sign-new-book"
QIDIAN_RANKING_URL = "https://www.qidian.com/rank/signNewBkAll/"
QIDIAN_BOOK_HOST = "www.qidian.com"
QIDIAN_PAGE_SIZE = 20
_BOOK_PATH = re.compile(r"^/book/(\d+)/?$", re.IGNORECASE)


class RankingParseError(ValueError):
    """Raised when a ranking page is incomplete or its structure is unexpected."""


class RankingAccessError(RankingParseError):
    """Raised when the ranking explicitly requires unavailable access."""


@dataclass(frozen=True)
class RankingPage:
    page_number: int
    candidates: Tuple[BookCandidate, ...]
    has_next: Optional[bool] = None


@dataclass(frozen=True)
class RankingSnapshot:
    candidates: Tuple[BookCandidate, ...]
    snapshot_at: datetime
    source_exhausted: bool


class QidianRankingProvider:
    """Read and parse Qidian's signed-new-book ranking."""

    platform = "qidian"
    ranking_id = QIDIAN_RANKING_ID
    ranking_url = QIDIAN_RANKING_URL
    page_size = QIDIAN_PAGE_SIZE

    @staticmethod
    def page_url(page_number: int) -> str:
        if page_number < 1:
            raise ValueError("page_number must be at least 1")
        if page_number == 1:
            return QIDIAN_RANKING_URL
        return f"{QIDIAN_RANKING_URL}page{page_number}/"

    def fetch_page(self, page_number: int, scraper: Scraper) -> RankingPage:
        """Render a ranking page and verify its visible pagination boundary."""
        url = self.page_url(page_number)
        for _attempt in range(2):
            page = scraper.render_soup(
                url,
                wait_for='li[data-rid] a[href*="/book/"]',
                timeout=45,
            )
            html = page.outer_html
            soup = BeautifulSoup(html, "html.parser")
            if soup.select('li[data-rid] a[href*="/book/"]'):
                break
            page_text = soup.get_text(" ", strip=True)
            if any(
                marker in page_text
                for marker in ("验证码", "访问被拒绝", "请登录后访问", "需要登录")
            ):
                raise RankingAccessError("Qidian ranking access was refused")
        else:
            raise RankingParseError("Ranking entries are absent after rendering twice")
        next_path = urlsplit(self.page_url(page_number + 1)).path
        has_next = any(
            urlsplit(urljoin(url, str(anchor.get("href") or ""))).path == next_path
            for anchor in soup.select('a[href*="signNewBkAll/page"]')
        )
        result = self.parse_page(html, page_number=page_number, has_next=has_next)
        if has_next and len(result.candidates) != self.page_size:
            raise RankingParseError(
                f"Ranking page {page_number} has a next page but only "
                f"{len(result.candidates)} entries"
            )
        return result

    def discover(self, max_candidates: int, scraper: Scraper) -> RankingSnapshot:
        """Read pages only until the scan limit or confirmed last page."""

        def pages() -> Iterable[RankingPage]:
            page_number = 1
            while True:
                page = self.fetch_page(page_number, scraper)
                yield page
                if page.has_next is False:
                    return
                page_number += 1

        return freeze_pages(pages(), max_candidates=max_candidates)

    def parse_page(
        self,
        html: str,
        page_number: int = 1,
        has_next: Optional[bool] = None,
    ) -> RankingPage:
        """Parse one page and preserve source order and each ``data-rid`` value."""
        if page_number < 1:
            raise ValueError("page_number must be at least 1")
        soup = BeautifulSoup(html, "html.parser")
        entries = soup.select("li[data-rid]")
        if not entries:
            raise RankingParseError("No li[data-rid] ranking entries were found")
        if len(entries) > self.page_size:
            raise RankingParseError(
                f"Ranking page has {len(entries)} entries; expected at most {self.page_size}"
            )

        candidates = []
        for entry_number, entry in enumerate(entries, start=1):
            candidates.append(self._parse_entry(entry, entry_number, page_number))
        return RankingPage(
            page_number=page_number,
            candidates=tuple(candidates),
            has_next=has_next,
        )

    def _parse_entry(self, entry: Tag, entry_number: int, page_number: int) -> BookCandidate:
        rank_tag = entry.select_one(".rank-tag")
        if page_number > 1 and rank_tag is None:
            raise RankingParseError(
                f"Ranking entry {entry_number} on page {page_number} has no displayed rank"
            )
        rank_value = (
            self._text(rank_tag)
            if rank_tag is not None
            else str(entry.get("data-rid") or "").strip()
        )
        if not rank_value.isdecimal() or int(rank_value) < 1:
            raise RankingParseError(f"Ranking entry {entry_number} has a missing or invalid rank")

        book_links = []
        for anchor in entry.select("a[href]"):
            href = str(anchor.get("href") or "").strip()
            if self._book_id_from_url(href) is not None:
                book_links.append((anchor, href))
        book_ids = {self._book_id_from_url(href) for _, href in book_links}
        if len(book_ids) != 1 or None in book_ids:
            raise RankingParseError(
                f"Ranking entry {entry_number} must contain exactly one valid Qidian book URL"
            )

        href = book_links[0][1]
        external_book_id = next(iter(book_ids))
        title_anchor = next((anchor for anchor, _ in book_links if anchor.find_parent("h2")), None)
        if title_anchor is None:
            title_anchor = next(
                (anchor for anchor, _ in book_links if self._text(anchor) != "书籍详情"),
                book_links[0][0],
            )
        title = self._first_text(
            (
                self._text(title_anchor),
                str(title_anchor.get("title") or ""),
                str(title_anchor.get("aria-label") or ""),
            )
        )
        if not title:
            raise RankingParseError(f"Ranking entry {entry_number} has no book title")

        author = self._semantic_text(
            entry,
            (
                '[data-role="author"]',
                ".author .name",
                'a[href*="/author/"]',
                "a.author",
                ".author",
                '[class*="author"]',
            ),
        )
        if not author:
            raise RankingParseError(f"Ranking entry {entry_number} has no author")

        category = self._semantic_text(
            entry,
            (
                "p.author a:not(.name)",
                '[data-role="category"]',
                ".category",
                'a[href*="/category/"]',
                '[class*="category"]',
            ),
        )
        book_url = self._canonical_book_url(href)
        return BookCandidate(
            platform=self.platform,
            ranking_id=self.ranking_id,
            external_book_id=str(external_book_id),
            book_url=book_url,
            title=title,
            author=author,
            category=category or None,
            original_rank=int(rank_value),
        )

    @staticmethod
    def _text(node: Tag) -> str:
        return " ".join(node.stripped_strings).strip()

    @classmethod
    def _first_text(cls, values: Iterable[str]) -> str:
        for value in values:
            text = " ".join(value.split()).strip()
            if text:
                return text
        return ""

    @classmethod
    def _semantic_text(cls, entry: Tag, selectors: Tuple[str, ...]) -> str:
        for selector in selectors:
            node = entry.select_one(selector)
            if node is not None:
                value = cls._text(node)
                if value:
                    return value
        return ""

    @staticmethod
    def _book_id_from_url(href: str) -> Optional[str]:
        url = urljoin(QIDIAN_RANKING_URL, href)
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or parts.hostname != QIDIAN_BOOK_HOST:
            return None
        match = _BOOK_PATH.fullmatch(parts.path)
        return match.group(1) if match else None

    @staticmethod
    def _canonical_book_url(href: str) -> str:
        url = urljoin(QIDIAN_RANKING_URL, href)
        parts = urlsplit(url)
        match = _BOOK_PATH.fullmatch(parts.path)
        if parts.hostname != QIDIAN_BOOK_HOST or match is None:
            raise RankingParseError("Book URL is not a canonical Qidian book page")
        return f"https://{QIDIAN_BOOK_HOST}/book/{match.group(1)}/"


def freeze_pages(
    pages: Iterable[RankingPage],
    max_candidates: int,
    snapshot_at: Optional[datetime] = None,
) -> RankingSnapshot:
    """Freeze a bounded page sequence without inferring cross-page rank offsets."""
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1")

    captured_at = snapshot_at or datetime.now(timezone.utc)
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("snapshot_at must be timezone-aware")
    captured_at = captured_at.astimezone(timezone.utc)

    candidates = []
    seen_ids = set()
    ranks = {}
    previous_rank = 0
    expected_page = 1
    source_key = None

    page_iterator = iter(pages)
    source_exhausted = False
    while len(candidates) < max_candidates:
        try:
            page = next(page_iterator)
        except StopIteration:
            if not candidates:
                raise RankingParseError("No ranking candidates were available to freeze")
            raise RankingParseError(
                f"Ranking page {expected_page} is missing before the scan limit was reached"
            )
        if page.page_number != expected_page:
            raise RankingParseError(
                f"Expected ranking page {expected_page}, received {page.page_number}"
            )
        expected_page += 1
        if not page.candidates:
            raise RankingParseError(f"Ranking page {page.page_number} is empty")

        for candidate in page.candidates:
            candidate_source = (candidate.platform, candidate.ranking_id)
            if source_key is None:
                source_key = candidate_source
            elif candidate_source != source_key:
                raise RankingParseError("A snapshot cannot mix ranking providers")

            if candidate.external_book_id in seen_ids:
                continue
            other_book_id = ranks.get(candidate.original_rank)
            if other_book_id is not None:
                raise RankingParseError(
                    f"Conflicting books share original rank {candidate.original_rank}"
                )
            if candidate.original_rank <= previous_rank:
                raise RankingParseError(
                    "Original ranks must increase in the supplied page order; "
                    "cross-page offsets are not inferred"
                )

            candidates.append(candidate)
            seen_ids.add(candidate.external_book_id)
            ranks[candidate.original_rank] = candidate.external_book_id
            previous_rank = candidate.original_rank
            if len(candidates) >= max_candidates:
                break

        if len(candidates) >= max_candidates:
            source_exhausted = page.has_next is False
            break
        if page.has_next is None:
            raise RankingParseError(
                f"Ranking page {page.page_number} does not identify whether another page exists"
            )
        if page.has_next is False:
            source_exhausted = True
            break

    return RankingSnapshot(tuple(candidates), captured_at, source_exhausted)
