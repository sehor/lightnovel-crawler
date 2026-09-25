"""Scoped Firefox browser reuse for batch rendering.

The pinned scraper engine opens a new browser for every render call. Keep its
normal behavior outside a batch, and keep proxy/profile identity and the global
browser slot inside one.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import logging
from pathlib import Path
import threading
import time
from typing import Any, Iterator, Optional, Tuple
from urllib.parse import urlsplit

from scraper import RenderError, SolveResult
from scraper.bidi import BidiSolver
from scraper.browser import browser_slot
from scraper.diagnosis import is_still_challenged
from scraper.wire import ProtocolError

logger = logging.getLogger(__name__)


class BatchBidiSolver(BidiSolver):
    """Retain one BiDi tab while a caller processes one Qidian batch.

    This adapter targets lncrawl-scraper 1.7.x. It uses the backend protocol
    connection because the package has no multi-page render interface yet.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._batch_gate = threading.RLock()
        self._batch_depth = 0
        self._active_key: Optional[Tuple[str, str, str]] = None
        self._active_stack: Optional[ExitStack] = None
        self._active_browser: Any = None

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Keep one browser until the enclosing operation finishes or fails."""
        with self._batch_gate:
            self._batch_depth += 1
            try:
                yield
            finally:
                self._batch_depth -= 1
                if self._batch_depth == 0:
                    self._release_browser()

    def _release_browser(self) -> None:
        stack, self._active_stack = self._active_stack, None
        self._active_browser = None
        self._active_key = None
        if stack is not None:
            stack.close()

    def _browser_for(self, url: str, proxy: Optional[str], profile_dir: Optional[Path]) -> Any:
        key = (urlsplit(url).hostname or "", proxy or "", str(profile_dir or ""))
        if self._active_key != key:
            self._release_browser()
            stack = ExitStack()
            try:
                stack.enter_context(browser_slot(self.engine))
                browser = stack.enter_context(self._browser(proxy, profile_dir))
                browser.attach()
            except BaseException:
                stack.close()
                raise
            self._active_stack = stack
            self._active_browser = browser
            self._active_key = key
        return self._active_browser

    @staticmethod
    def _navigate_interactive(browser: Any, url: str, timeout: float) -> None:
        """DOM readiness suffices; the selector poll decides content readiness."""
        try:
            browser._rpc.send(
                "browsingContext.navigate",
                {"context": browser._context, "url": url, "wait": "interactive"},
                timeout=timeout,
            )
        except ProtocolError:
            # A challenge can reload before navigation settles. Polling still
            # decides whether the requested page actually appeared.
            logger.debug("Navigation to %s did not settle; polling page", url, exc_info=True)

    def render(
        self,
        url: str,
        *,
        wait_for: Optional[str] = None,
        proxy: Optional[str] = None,
        profile_dir: Optional[Path] = None,
        timeout: float = 60.0,
    ) -> str:
        with self._batch_gate:
            if self._batch_depth == 0:
                return super().render(
                    url, wait_for=wait_for, proxy=proxy, profile_dir=profile_dir, timeout=timeout
                )
            with self._lock:
                deadline = time.monotonic() + timeout
                try:
                    browser = self._browser_for(url, proxy, profile_dir)
                    self._navigate_interactive(browser, url, timeout)
                    target = urlsplit(url)
                    if wait_for is None:
                        time.sleep(self._settle)
                    while time.monotonic() < deadline:
                        current = urlsplit(str(browser.evaluate("location.href") or ""))
                        same_page = current.hostname == target.hostname and current.path.rstrip(
                            "/"
                        ) == target.path.rstrip("/")
                        if same_page:
                            content = browser.content()
                            if not is_still_challenged(content):
                                if wait_for is None or browser.has(wait_for):
                                    return content
                        time.sleep(0.25)
                    missing = (
                        f"{wait_for} never appeared" if wait_for else "it was still a challenge"
                    )
                    raise RenderError(f"{url} did not render after {timeout:.0f}s: {missing}")
                except BaseException:
                    self._release_browser()
                    raise

    def solve(
        self,
        url: str,
        *,
        proxy: Optional[str] = None,
        profile_dir: Optional[Path] = None,
        timeout: float = 60.0,
    ) -> SolveResult:
        with self._batch_gate:
            self._release_browser()
            return super().solve(url, proxy=proxy, profile_dir=profile_dir, timeout=timeout)

    def close(self) -> None:
        with self._batch_gate:
            self._release_browser()
            super().close()
