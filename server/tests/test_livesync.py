"""LivesyncCli ラッパーのテスト（runner を差し替え）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import livesync  # noqa: E402

NPM = "/usr/bin/npm"
CLI_DIR = "/opt/cli"
DB_DIR = "/opt/db/"
VAULT_DIR = "/opt/vault/"


def make_cli(runner) -> livesync.LivesyncCli:
    return livesync.LivesyncCli(
        npm=NPM,
        cli_dir=CLI_DIR,
        db_dir=DB_DIR,
        vault_dir=VAULT_DIR,
        runner=runner,
    )


class LivesyncCliTest(unittest.TestCase):
    def test_subcommands_call_runner(self) -> None:
        called = []

        def runner(argv):
            called.append(list(argv))
            return 0

        cli = make_cli(runner)
        cli.sync()
        cli.mirror()
        cli.pull()
        cli.push()
        self.assertEqual(
            called,
            [
                [NPM, "--prefix", CLI_DIR, "run", "cli", "--", DB_DIR, "sync"],
                [NPM, "--prefix", CLI_DIR, "run", "cli", "--", DB_DIR, "mirror", VAULT_DIR],
                [NPM, "--prefix", CLI_DIR, "run", "cli", "--", DB_DIR, "pull", VAULT_DIR],
                [NPM, "--prefix", CLI_DIR, "run", "cli", "--", DB_DIR, "push", VAULT_DIR],
            ],
        )

    def test_sync_pull_combined(self) -> None:
        called = []

        def runner(argv):
            called.append(argv[7])  # subcommand is argv[7]

        cli = make_cli(runner)
        cli.sync_pull()
        self.assertEqual(called, ["sync", "pull"])
        called.clear()
        cli.push_sync()
        self.assertEqual(called, ["push", "sync"])

    def test_runner_failure_propagates(self) -> None:
        def runner(argv):
            raise livesync.LivesyncError("bad")

        cli = make_cli(runner)
        with self.assertRaises(livesync.LivesyncError):
            cli.sync()


if __name__ == "__main__":
    unittest.main()
