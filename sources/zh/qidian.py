"""Qidian book metadata and publicly available chapters."""

from decimal import Decimal, InvalidOperation
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
    count_pattern = r"\d[\d,]*(?:\.\d+)?\s*(?:亿|万|千)?"

    @staticmethod
    def parse_count(value: str) -> Optional[int]:
        normalized = value.strip().replace(",", "").replace("，", "").replace(" ", "")
        match = re.fullmatch(r"(?P<number>\d+(?:\.\d+)?)(?P<unit>亿|万|千)?(?:字)?", normalized)
        if not match:
            return None
        multiplier = {"亿": 100_000_000, "万": 10_000, "千": 1_000, None: 1}[match.group("unit")]
        try:
            return int(Decimal(match.group("number")) * multiplier)
        except InvalidOperation:
            return None

    @classmethod
    def count_before_label(cls, text: str, label_pattern: str) -> Optional[int]:
        match = re.search(rf"(?P<count>{cls.count_pattern})\s*{label_pattern}", text)
        return cls.parse_count(match.group("count")) if match else None

    @classmethod
    def count_after_label(cls, text: str, label: str) -> Optional[int]:
        match = re.search(rf"{re.escape(label)}\s*[:：]?\s*(?P<count>{cls.count_pattern})", text)
        return cls.parse_count(match.group("count")) if match else None

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
        tags = [category] if category else []
        tags.extend(
            tag.text.strip() for tag in soup.select(".all-label a.gray-hover") if tag.text.strip()
        )
        novel.tags = list(dict.fromkeys(tags))
        novel.ranking_names = self.parse_ranking_names(soup)
        self.parse_book_statistics(soup, novel)

    @staticmethod
    def parse_ranking_names(soup: PageSoup) -> list[str]:
        label = soup.select_one(".all-label")
        if not label:
            return []

        text = " ".join(label.text.split())
        for tag in label.select("a.gray-hover"):
            tag_text = " ".join(tag.text.split())
            if tag_text:
                text = text.replace(tag_text, " ", 1)

        return list(dict.fromkeys(re.findall(r"[\u4e00-\u9fffA-Za-z0-9·_-]+榜", text)))

    def parse_book_statistics(self, soup: PageSoup, novel: Novel) -> None:
        book_match = re.fullmatch(r"/(?:book|info)/(\d+)/?", urlsplit(novel.url).path)
        if book_match:
            novel.source_id = book_match.group(1)

        count = soup.select_one(".book-info-top .count")
        if count:
            statistics = " ".join(count.text.split())
            novel.word_count = self.count_before_label(statistics, r"(?:总)?字(?:数)?")
            novel.total_recommendations = self.count_before_label(statistics, r"总推荐")
            novel.weekly_recommendations = self.count_before_label(statistics, r"周推荐")

        reward = soup.select_one(".reward-info")
        if reward:
            novel.weekly_tipper_count = self.count_after_label(
                " ".join(reward.text.split()), "本周打赏人数"
            )

        author_info = soup.select_one(".author-information")
        if author_info:
            author_text = " ".join(author_info.text.split())
            work_state = author_info.select_one(".work-state") or author_info
            work_text = " ".join(work_state.text.split())
            novel.author_work_count = self.count_after_label(work_text, "作品总数")
            novel.author_total_word_count = self.count_after_label(work_text, "累计字数")
            novel.author_creation_days = self.count_after_label(work_text, "创作天数")

            level = author_info.select_one('[class*="level-"]')
            if level:
                novel.author_level = level.text.strip() or None
            else:
                level_match = re.search(r"白金|大神", author_text)
                if level_match:
                    novel.author_level = level_match.group(0)

    def parse_toc(self, soup: PageSoup, novel: Novel) -> None:
        page_text = " ".join(soup.text.split())
        published_count = self.count_after_label(page_text, "目录连载共")
        if published_count is None:
            counts = []
            for volume in soup.select(self.volume_list_selector):
                volume_title = volume.select_one(self.volume_title_selector)
                if not volume_title:
                    continue
                match = re.search(
                    rf"共\s*(?P<count>{self.count_pattern})\s*章",
                    " ".join(volume_title.text.split()),
                )
                if match:
                    count = self.parse_count(match.group("count"))
                    if count is not None:
                        counts.append(count)
            if counts:
                published_count = sum(counts)

        if published_count is None:
            book_match = re.fullmatch(r"/(?:book|info)/(\d+)/?", urlsplit(novel.url).path)
            if book_match:
                chapter_path = re.compile(rf"/chapter/{book_match.group(1)}/\d+/?")
                published_count = sum(
                    1
                    for volume in soup.select(self.volume_list_selector)
                    for anchor in volume.select(self.chapter_list_selector)
                    if chapter_path.fullmatch(urlsplit(self.absolute_url(anchor.get("href"))).path)
                )

        novel.source_chapter_count = published_count
        super().parse_toc(soup, novel)

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
