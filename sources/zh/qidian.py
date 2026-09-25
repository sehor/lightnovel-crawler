"""Qidian book metadata and publicly available chapters."""

import re
from typing import Iterable, Optional
from urllib.parse import urlsplit

from scraper import PageSoup

from lncrawl.core import Chapter, Novel, SoupTemplate, Volume
from lncrawl.exceptions import LNException


class Qidian(SoupTemplate):
    base_url = ["https://www.qidian.com/", "https://book.qidian.com/"]
    language = "zh"
    request_rate_limit = 0.1

    novel_title_selector = "#bookName"
    volume_list_selector = ".catalog-volume"
    volume_title_selector = ".volume-name"
    chapter_list_selector = ".volume-chapters > li.chapter-item > a.chapter-name[href]"
    chapter_body_selector = "main.content[id^='c-']"

    def get_novel_soup(self, novel: Novel) -> PageSoup:
        """Use the current book URL and wait for the rendered catalog."""
        path = urlsplit(novel.url).path
        old_book = re.fullmatch(r"/info/(\d+)/?", path)
        url = f"https://www.qidian.com/book/{old_book.group(1)}/" if old_book else novel.url
        return self.scraper.render_soup(url, wait_for=self.volume_list_selector)

    def parse_authors(self, soup: PageSoup, novel: Novel) -> None:
        novel.author = str(
            soup.select_one('meta[property="og:novel:author"]').get("content") or ""
        ).strip()

    def parse_tags(self, soup: PageSoup, novel: Novel) -> None:
        category = str(
            soup.select_one('meta[property="og:novel:category"]').get("content") or ""
        ).strip()
        novel.tags = [category] if category else []

    def select_volume_tags(self, soup: PageSoup, novel: Novel) -> Iterable[PageSoup]:
        for volume in soup.select(self.volume_list_selector):
            label = volume.select_one(self.volume_title_selector).text.strip()
            if "免费" in label and "VIP" not in label.upper():
                yield volume

    def select_chapter_tags(
        self, tag: PageSoup, novel: Novel, volume: Optional[Volume] = None
    ) -> Iterable[PageSoup]:
        book_match = re.fullmatch(r"/(?:book|info)/(\d+)/?", urlsplit(novel.url).path)
        if not book_match or volume is None:
            return []
        book_id = book_match.group(1)
        chapter_path = re.compile(rf"/chapter/{book_id}/\d+/?")
        return [
            anchor
            for anchor in tag.select(self.chapter_list_selector)
            if urlsplit(self.absolute_url(anchor.get("href"))).hostname == "www.qidian.com"
            and chapter_path.fullmatch(urlsplit(self.absolute_url(anchor.get("href"))).path)
            and not anchor.closest(".vip, .locked, .paid")
        ]

    def download_chapter(self, chapter: Chapter) -> None:
        # Qidian's chapter endpoint fails as a plain request but renders in the
        # shared scraper browser, which also retains the site's clearance.
        soup = self.scraper.render_soup(
            self.build_chapter_url(chapter), wait_for=self.chapter_body_selector
        )
        body = soup.select_one(self.chapter_body_selector)
        if not body:
            raise LNException(f"Failed to find Qidian chapter body: {chapter.url}")
        self.parse_chapter_body(body, chapter)
        if not chapter.body:
            raise LNException(f"Empty Qidian chapter body: {chapter.url}")
