"""Offline parser and frozen-candidate checks using synthetic markup only."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

from research.models import BookCandidate
from research.ranking.qidian import (
    QIDIAN_RANKING_ID,
    QidianRankingProvider,
    RankingAccessError,
    RankingPage,
    RankingParseError,
    freeze_pages,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class QidianRankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = QidianRankingProvider()

    def test_synthetic_page_extracts_fields_and_keeps_source_rank(self) -> None:
        html = (FIXTURE_DIR / "sign_new_book_page1.html").read_text(encoding="utf-8")
        page = self.provider.parse_page(html)
        self.assertEqual(len(page.candidates), 2)
        first, second = page.candidates
        self.assertEqual(first.platform, "qidian")
        self.assertEqual(first.ranking_id, QIDIAN_RANKING_ID)
        self.assertEqual(first.external_book_id, "90000001")
        self.assertEqual(first.book_url, "https://www.qidian.com/book/90000001/")
        self.assertEqual(first.title, "Synthetic Moon Harbor")
        self.assertEqual(first.author, "Example Author One")
        self.assertEqual(first.category, "Fantasy")
        self.assertEqual(first.original_rank, 1)
        self.assertIsNone(second.category)
        self.assertEqual(second.original_rank, 2)
        self.assertEqual(
            second.book_url,
            "https://www.qidian.com/book/90000002/",
        )

    def test_missing_required_rank_or_metadata_fails_closed(self) -> None:
        with self.assertRaisesRegex(RankingParseError, "invalid rank"):
            self.provider.parse_page(
                '<li data-rid=""><a href="/book/90000001/">Title</a>'
                '<span class="author">Author</span></li>'
            )
        with self.assertRaisesRegex(RankingParseError, "exactly one valid"):
            self.provider.parse_page('<li data-rid="1"><span>Incomplete</span></li>')

    def test_page_with_unrecognized_structure_fails(self) -> None:
        with self.assertRaisesRegex(RankingParseError, r"No li\[data-rid\]"):
            self.provider.parse_page("<ul><li>changed markup</li></ul>")

    def test_page_rejects_more_entries_than_observed_page_size(self) -> None:
        entry = "<li data-rid='1'></li>"
        html = f"<ul>{entry * 21}</ul>"
        with self.assertRaisesRegex(RankingParseError, "expected at most 20"):
            self.provider.parse_page(html)

    def test_freeze_deduplicates_without_renumbering_and_uses_one_utc_time(self) -> None:
        first, second = self.provider.parse_page(
            (FIXTURE_DIR / "sign_new_book_page1.html").read_text(encoding="utf-8")
        ).candidates
        duplicate = BookCandidate(
            platform=first.platform,
            ranking_id=first.ranking_id,
            external_book_id=first.external_book_id,
            book_url=first.book_url,
            title=first.title,
            author=first.author,
            category=first.category,
            original_rank=3,
        )
        snapshot_time = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)
        frozen = freeze_pages(
            [
                RankingPage(1, (first, second), has_next=True),
                RankingPage(2, (duplicate,), has_next=False),
            ],
            max_candidates=10,
            snapshot_at=snapshot_time,
        )
        self.assertEqual(
            [candidate.external_book_id for candidate in frozen.candidates],
            ["90000001", "90000002"],
        )
        self.assertEqual([candidate.original_rank for candidate in frozen.candidates], [1, 2])
        self.assertEqual(frozen.snapshot_at, snapshot_time)
        self.assertTrue(frozen.source_exhausted)

    def test_freeze_rejects_page_gaps_and_conflicting_or_local_ranks(self) -> None:
        first, second = self.provider.parse_page(
            (FIXTURE_DIR / "sign_new_book_page1.html").read_text(encoding="utf-8")
        ).candidates
        other_book_same_rank = BookCandidate(
            platform=second.platform,
            ranking_id=second.ranking_id,
            external_book_id="90000003",
            book_url="https://www.qidian.com/book/90000003/",
            title="Synthetic Copper Lake",
            author="Example Author Three",
            category=None,
            original_rank=2,
        )
        page_one_second = BookCandidate(
            platform=second.platform,
            ranking_id=second.ranking_id,
            external_book_id=second.external_book_id,
            book_url=second.book_url,
            title=second.title,
            author=second.author,
            category=second.category,
            original_rank=3,
        )
        cross_page_local_rank = BookCandidate(
            platform=second.platform,
            ranking_id=second.ranking_id,
            external_book_id="90000004",
            book_url="https://www.qidian.com/book/90000004/",
            title="Synthetic Glass Orchard",
            author="Example Author Four",
            category=None,
            original_rank=2,
        )
        with self.assertRaisesRegex(RankingParseError, "Expected ranking page 1"):
            freeze_pages([RankingPage(2, (first,))], max_candidates=1)
        with self.assertRaisesRegex(RankingParseError, "Conflicting books share"):
            freeze_pages(
                [
                    RankingPage(1, (first, second), has_next=True),
                    RankingPage(2, (other_book_same_rank,), has_next=False),
                ],
                10,
            )
        with self.assertRaisesRegex(RankingParseError, "cross-page offsets are not inferred"):
            freeze_pages(
                [
                    RankingPage(1, (first, page_one_second), has_next=True),
                    RankingPage(2, (cross_page_local_rank,), has_next=False),
                ],
                max_candidates=10,
            )

    def test_freeze_rejects_empty_page_and_naive_snapshot_time(self) -> None:
        with self.assertRaisesRegex(RankingParseError, "page 1 is empty"):
            freeze_pages([RankingPage(1, ())], max_candidates=10)
        first = self.provider.parse_page(
            (FIXTURE_DIR / "sign_new_book_page1.html").read_text(encoding="utf-8")
        ).candidates[0]
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            freeze_pages([RankingPage(1, (first,), has_next=False)], 1, datetime(2026, 9, 24))

    def test_freeze_rejects_unknown_or_missing_page_boundaries(self) -> None:
        first = self.provider.parse_page(
            (FIXTURE_DIR / "sign_new_book_page1.html").read_text(encoding="utf-8")
        ).candidates[0]
        with self.assertRaisesRegex(RankingParseError, "does not identify"):
            freeze_pages([RankingPage(1, (first,))], max_candidates=10)
        with self.assertRaisesRegex(RankingParseError, "page 2 is missing"):
            freeze_pages([RankingPage(1, (first,), has_next=True)], max_candidates=10)

    def test_freeze_stops_at_scan_limit_without_requesting_another_page(self) -> None:
        first = self.provider.parse_page(
            (FIXTURE_DIR / "sign_new_book_page1.html").read_text(encoding="utf-8")
        ).candidates[0]

        def pages():
            yield RankingPage(1, (first,), has_next=True)
            raise AssertionError("freeze_pages requested a page after reaching its limit")

        frozen = freeze_pages(pages(), max_candidates=1)
        self.assertEqual(len(frozen.candidates), 1)
        self.assertFalse(frozen.source_exhausted)

    def test_page_two_uses_displayed_rank_and_semantic_book_fields(self) -> None:
        html = """
        <li data-rid="1">
          <span class="rank-tag">21</span>
          <a href="//www.qidian.com/book/90000021/"></a>
          <div class="book-mid-info">
            <h2><a href="//www.qidian.com/book/90000021/">Synthetic North Star</a></h2>
            <p class="author">
              <a class="name" href="//my.qidian.com/author/1/">Example Author</a>
              <a href="//www.qidian.com/all/chanId1/">Fantasy</a>
            </p>
          </div>
          <a href="//www.qidian.com/book/90000021/">书籍详情</a>
        </li>
        """
        candidate = self.provider.parse_page(html, page_number=2).candidates[0]
        self.assertEqual(candidate.original_rank, 21)
        self.assertEqual(candidate.title, "Synthetic North Star")
        self.assertEqual(candidate.author, "Example Author")
        self.assertEqual(candidate.category, "Fantasy")
        with self.assertRaisesRegex(RankingParseError, "no displayed rank"):
            self.provider.parse_page(
                html.replace('<span class="rank-tag">21</span>', ""), page_number=2
            )

    def test_live_adapter_follows_only_needed_pages(self) -> None:
        def row(number: int, rank: int) -> str:
            return (
                f'<li data-rid="{number}"><span class="rank-tag">{rank}</span>'
                f'<h2><a href="/book/{90000000 + rank}/">Book {rank}</a></h2>'
                '<a class="author" href="/author/1/">Author</a></li>'
            )

        first_page = "<ul>" + "".join(row(i, i) for i in range(1, 21)) + "</ul>"
        first_page += '<a href="/rank/signNewBkAll/page2/">2</a>'
        second_page = "<ul>" + row(1, 21) + "</ul>"

        class FakeScraper:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def render_soup(self, url: str, **_kwargs: object) -> SimpleNamespace:
                self.urls.append(url)
                html = first_page if len(self.urls) == 1 else second_page
                return SimpleNamespace(outer_html=html)

        scraper = FakeScraper()
        snapshot = self.provider.discover(21, scraper)  # type: ignore[arg-type]
        self.assertEqual([item.original_rank for item in snapshot.candidates], list(range(1, 22)))
        self.assertEqual(
            scraper.urls,
            [self.provider.page_url(1), self.provider.page_url(2)],
        )
        self.assertTrue(snapshot.source_exhausted)

    def test_incomplete_render_retries_once_but_refusal_stops(self) -> None:
        valid = (FIXTURE_DIR / "sign_new_book_page1.html").read_text(encoding="utf-8")

        class FakeScraper:
            def __init__(self, pages: list[str]) -> None:
                self.pages = pages
                self.calls = 0

            def render_soup(self, _url: str, **_kwargs: object) -> SimpleNamespace:
                page = self.pages[self.calls]
                self.calls += 1
                return SimpleNamespace(outer_html=page)

        scraper = FakeScraper(["<html><title>Loading</title></html>", valid])
        result = self.provider.fetch_page(1, scraper)  # type: ignore[arg-type]
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(scraper.calls, 2)

        refused = FakeScraper(["<html><body>验证码</body></html>"])
        with self.assertRaises(RankingAccessError):
            self.provider.fetch_page(1, refused)  # type: ignore[arg-type]
        self.assertEqual(refused.calls, 1)


if __name__ == "__main__":
    unittest.main()
