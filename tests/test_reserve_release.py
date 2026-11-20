from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/reserve_release.py"


class ReleaseReservationTests(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory(prefix="scrapbook-release-")
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.remote = self.root / "remote.git"
        self.first = self.root / "hlg"
        self.second = self.root / "main"
        self.git(self.root, "init", "--quiet", "--bare", str(self.remote))
        self.git(self.root, "clone", "--quiet", str(self.remote), str(self.first))
        self.configure(self.first)
        self.git(self.first, "checkout", "--quiet", "-b", "hlg")
        self.git(self.first, "commit", "--quiet", "--allow-empty", "-m", "Homologação")
        self.git(self.first, "push", "--quiet", "origin", "hlg")
        self.git(self.root, "clone", "--quiet", "--branch", "hlg", str(self.remote), str(self.second))
        self.configure(self.second)
        self.git(self.second, "checkout", "--quiet", "-b", "main")
        self.git(self.second, "commit", "--quiet", "--allow-empty", "-m", "Produção")
        self.git(self.second, "push", "--quiet", "origin", "main")

    def configure(self, directory):
        self.git(directory, "config", "user.name", "ScrapBook fixture")
        self.git(directory, "config", "user.email", "fixture@example.test")
        self.git(directory, "config", "commit.gpgsign", "false")

    @staticmethod
    def git(directory, *args):
        return subprocess.check_output(["git", "-C", str(directory), *args], text=True).strip()

    def reserve(self, directory, run, series="1.0", sha=None):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), series, sha or self.git(directory, "rev-parse", "HEAD"), run],
            cwd=directory, text=True, capture_output=True, timeout=30,
        )

    def assert_reservation(self, result):
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.strip()

    def test_hlg_and_main_reserve_distinct_tags_on_the_same_remote(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.reserve, self.first, "100.1")
            second = pool.submit(self.reserve, self.second, "101.1")
            versions = [self.assert_reservation(first.result()), self.assert_reservation(second.result())]
        self.assertEqual({"v1.0.0", "v1.0.1"}, set(versions))
        for version, directory in zip(versions, (self.first, self.second)):
            self.assertEqual("tag", self.git(self.remote, "cat-file", "-t", version))
            self.assertEqual(self.git(directory, "rev-parse", "HEAD"), self.git(self.remote, "rev-parse", version + "^{}"))

    def test_recovery_of_same_attempt_and_new_attempt(self):
        self.assertEqual("v1.0.0", self.assert_reservation(self.reserve(self.first, "100.1")))
        self.assertEqual("v1.0.0", self.assert_reservation(self.reserve(self.first, "100.1")))
        self.assertEqual("v1.0.1", self.assert_reservation(self.reserve(self.first, "100.2")))
        conflict = self.reserve(self.second, "100.1")
        self.assertEqual(1, conflict.returncode)
        self.assertIn("reserva incompatível", conflict.stderr)

    def test_lightweight_tag_is_rejected(self):
        self.git(self.first, "push", "--quiet", "origin", "HEAD:refs/tags/v1.0.0")
        result = self.reserve(self.first, "100.1")
        self.assertEqual(1, result.returncode)
        self.assertIn("tag anotada", result.stderr)

    def test_invalid_series_revision_or_run_is_rejected(self):
        for options in ({"series": "1.0.0"}, {"sha": "0" * 40}):
            self.assertEqual(1, self.reserve(self.first, "100.1", **options).returncode)
        self.assertEqual(1, self.reserve(self.first, "wrong").returncode)


if __name__ == "__main__":
    unittest.main()
