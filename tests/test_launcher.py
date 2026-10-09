# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import os
import signal
import subprocess
import tempfile
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPOSITORY_ROOT / "bin" / "findhub-relay"


class LauncherBehaviorTests(unittest.TestCase):
    def make_python(self, directory, body):
        executable = Path(directory) / "python"
        executable.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        executable.chmod(0o755)
        return executable

    def test_forwards_arguments_output_and_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_python(
                directory,
                "printf '%s\\n' \"$@\"\nprintf 'forwarded stderr\\n' >&2\nexit 37\n",
            )
            result = subprocess.run(
                [LAUNCHER, "once", "argument with spaces", "--flag=value"],
                env={"PATH": directory},
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 37)
        self.assertEqual(
            result.stdout.splitlines(),
            ["-m", "findhub_relay", "once", "argument with spaces", "--flag=value"],
        )
        self.assertEqual(result.stderr, "forwarded stderr\n")

    def test_exec_preserves_python_signal_status(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_python(directory, "kill -TERM $$\n")
            result = subprocess.run(
                [LAUNCHER, "daemon"],
                env={"PATH": directory},
                check=False,
            )

        self.assertEqual(result.returncode, -signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
