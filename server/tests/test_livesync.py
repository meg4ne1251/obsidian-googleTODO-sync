"""LivesyncCli ラッパーのテスト（runner を差し替え）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import livesync  # noqa: E402


class LivesyncCliTest(unittest.TestCase):
    def test_subcommands_call_runner(self) -> None:
        called = []

        def runner(argv):
            called.append(list(argv))
            return 0

        cli = livesync.LivesyncCli(cli_command="livesync-cli", runner=runner)
        cli.sync()
        cli.mirror()
        cli.pull()
        cli.push()
        self.assertEqual(
            called,
            [
                ["livesync-cli", "sync"],
                ["livesync-cli", "mirror"],
                ["livesync-cli", "pull"],
                ["livesync-cli", "push"],
            ],
        )

    def test_sync_pull_combined(self) -> None:
        called = []
        cli = livesync.LivesyncCli(runner=lambda argv: called.append(argv[1]))
        cli.sync_pull()
        self.assertEqual(called, ["sync", "pull"])
        called.clear()
        cli.push_sync()
        self.assertEqual(called, ["push", "sync"])

    def test_runner_failure_propagates(self) -> None:
        def runner(argv):
            raise livesync.LivesyncError("bad")

        cli = livesync.LivesyncCli(runner=runner)
        with self.assertRaises(livesync.LivesyncError):
            cli.sync()


if __name__ == "__main__":
    unittest.main()
