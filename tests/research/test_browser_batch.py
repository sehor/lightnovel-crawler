"""Regression checks for the scoped Firefox render session."""

from contextlib import nullcontext
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from scraper import RenderError

from lncrawl.services.browser_batch import BatchBidiSolver


class FakeRpc:
    def __init__(self, browser: "FakeBrowser") -> None:
        self.browser = browser
        self.wait_modes = []

    def send(self, method: str, params: dict, timeout: float) -> dict:
        assert method == "browsingContext.navigate"
        self.wait_modes.append(params["wait"])
        self.browser.url = params["url"]
        return {}


class FakeBrowser:
    def __init__(self) -> None:
        self.url = ""
        self._context = "tab-1"
        self._rpc = FakeRpc(self)
        self.attach_count = 0

    def attach(self) -> None:
        self.attach_count += 1

    def evaluate(self, expression: str) -> str:
        assert expression == "location.href"
        return self.url

    def content(self) -> str:
        return "<html><body><main class='content'><p>Chapter</p></main></body></html>"

    def has(self, selector: str) -> bool:
        return selector == "main.content p"


class FakeSession:
    def __init__(self) -> None:
        self.browser = FakeBrowser()
        self.opens = 0
        self.closes = 0

    def __enter__(self) -> FakeBrowser:
        self.opens += 1
        return self.browser

    def __exit__(self, *_args: object) -> None:
        self.closes += 1


class BatchBidiSolverTests(TestCase):
    def test_two_pages_share_one_tab_and_close_after_batch(self) -> None:
        solver = BatchBidiSolver(executable="firefox", settle=0)
        session = FakeSession()
        with (
            patch.object(solver, "_browser", return_value=session),
            patch("lncrawl.services.browser_batch.browser_slot", return_value=nullcontext()),
        ):
            with solver.batch():
                for number in (1, 2):
                    html = solver.render(
                        f"https://www.qidian.com/chapter/1/{number}",
                        wait_for="main.content p",
                        profile_dir=Path("qidian-profile"),
                    )
                    self.assertIn("Chapter", html)
                self.assertEqual(session.opens, 1)
                self.assertEqual(session.closes, 0)
            self.assertEqual(session.closes, 1)
        self.assertEqual(session.browser.attach_count, 1)
        self.assertEqual(session.browser._rpc.wait_modes, ["interactive", "interactive"])

    def test_identity_change_closes_old_browser(self) -> None:
        solver = BatchBidiSolver(executable="firefox", settle=0)
        first, second = FakeSession(), FakeSession()
        with (
            patch.object(solver, "_browser", side_effect=[first, second]),
            patch("lncrawl.services.browser_batch.browser_slot", return_value=nullcontext()),
        ):
            with solver.batch():
                solver.render("https://www.qidian.com/book/1/", profile_dir=Path("first"))
                solver.render("https://www.qidian.com/book/2/", profile_dir=Path("second"))
                self.assertEqual(first.closes, 1)
                self.assertEqual(second.closes, 0)
            self.assertEqual(second.closes, 1)

    def test_failed_render_releases_browser(self) -> None:
        solver = BatchBidiSolver(executable="firefox", settle=0)
        session = FakeSession()
        with (
            patch.object(solver, "_browser", return_value=session),
            patch("lncrawl.services.browser_batch.browser_slot", return_value=nullcontext()),
        ):
            with solver.batch():
                with self.assertRaises(RenderError):
                    solver.render(
                        "https://www.qidian.com/chapter/1/1",
                        wait_for="#missing",
                        profile_dir=Path("qidian-profile"),
                        timeout=0.001,
                    )
                self.assertEqual(session.closes, 1)
