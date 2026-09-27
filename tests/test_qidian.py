"""Focused offline checks for Qidian's free catalog and rendered chapters."""

import unittest
from unittest.mock import Mock

from bs4 import BeautifulSoup
from scraper import PageSoup

from lncrawl.core import Chapter, Novel
from lncrawl.core.cleaner import TextCleaner
from lncrawl.exceptions import LNException
from sources.zh.qidian import Qidian

BOOK_URL = "https://www.qidian.com/book/1887208/"
OLD_BOOK_URL = "https://book.qidian.com/info/1887208/"
CHAPTER_URL = "https://www.qidian.com/chapter/1887208/31770804"

BOOK_HTML = """
<html>
  <head>
    <meta property="og:image" content="https://www.qidian.com/cover.jpg">
    <meta property="og:novel:author" content="作者">
    <meta property="og:novel:category" content="游戏">
    <meta property="og:description" content="简介">
  </head>
  <body>
    <h1 id="bookName">测试小说</h1>
    <div class="catalog-volume">
      <div class="volume-name">免费卷</div>
      <ul class="volume-chapters">
        <li class="chapter-item"><a class="chapter-name"
          href="/chapter/1887208/31770804">第一章</a></li>
        <li class="chapter-item vip"><a class="chapter-name"
          href="/chapter/1887208/31770805">收费章</a></li>
        <li class="chapter-item"><a class="chapter-name"
          href="/chapter/999999/1">其他书章节</a></li>
      </ul>
    </div>
    <div class="catalog-volume">
      <div class="volume-name">VIP卷</div>
      <ul class="volume-chapters">
        <li class="chapter-item"><a class="chapter-name"
          href="/chapter/1887208/31770806">第二卷收费章</a></li>
      </ul>
    </div>
  </body>
</html>
"""


def make_soup(html: str) -> PageSoup:
    return PageSoup(BeautifulSoup(html, "html.parser"))


def make_crawler(html: str) -> Qidian:
    crawler = Qidian.__new__(Qidian)
    crawler.scraper = Mock(last_url=BOOK_URL)
    crawler.scraper.render_soup.return_value = make_soup(html)
    crawler.cleaner = TextCleaner()
    return crawler


class QidianTests(unittest.TestCase):
    def test_current_and_old_book_urls_select_only_free_chapters(self) -> None:
        for url in (BOOK_URL, OLD_BOOK_URL):
            with self.subTest(url=url):
                crawler = make_crawler(BOOK_HTML)
                novel = Novel(url=url)

                crawler.read_novel(novel)

                self.assertEqual(novel.title, "测试小说")
                self.assertEqual(novel.author, "作者")
                self.assertEqual(novel.tags, ["游戏"])
                self.assertEqual([chapter.title for chapter in novel.chapters], ["第一章"])
                self.assertEqual(novel.chapters[0].url, CHAPTER_URL)
                crawler.scraper.render_soup.assert_called_once_with(
                    BOOK_URL if url == OLD_BOOK_URL else url,
                    wait_for=crawler.volume_list_selector,
                )

    def test_download_renders_and_extracts_chapter_body(self) -> None:
        crawler = make_crawler('<main class="content" id="c-31770804"><p>正文第一段。</p></main>')
        chapter = Chapter(id=1, url=CHAPTER_URL)

        crawler.download_chapter(chapter)

        self.assertIn("正文第一段。", chapter.body)
        crawler.scraper.render_soup.assert_called_once_with(
            CHAPTER_URL, wait_for=crawler.chapter_body_selector
        )

    def test_download_rejects_missing_or_empty_body(self) -> None:
        for html in ("<main></main>", '<main class="content" id="c-1"></main>'):
            with self.subTest(html=html):
                crawler = make_crawler(html)
                chapter = Chapter(id=1, url=CHAPTER_URL)
                with self.assertRaises(LNException):
                    crawler.download_chapter(chapter)


if __name__ == "__main__":
    unittest.main()
