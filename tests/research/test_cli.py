"""Offline checks for command defaults and unfinished command behavior."""

from pathlib import Path
import unittest

from typer.testing import CliRunner

from research.cli import CollectOptions, app


class ResearchCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_collect_defaults_match_contract(self) -> None:
        options = CollectOptions()
        self.assertEqual(options.target_books, 10)
        self.assertEqual(options.chapters, 5)
        self.assertEqual(options.max_candidates, 50)
        self.assertEqual(options.db, Path("data/research.db"))

    def test_collect_rejects_candidate_limit_below_target(self) -> None:
        result = self.runner.invoke(
            app,
            ["collect", "--target-books", "10", "--max-candidates", "9"],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("max-candidates", result.output)

    def test_export_rejects_unknown_run_without_false_success(self) -> None:
        result = self.runner.invoke(
            app,
            ["export", "--run-id", "sample", "--format", "jsonl", "--output", "unused"],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("export failed", result.output)

    def test_help_lists_the_contract_commands(self) -> None:
        result = self.runner.invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0)
        for command in ("collect", "resume", "export", "status"):
            self.assertIn(command, result.output)


if __name__ == "__main__":
    unittest.main()
