import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from runner import plan, run


class RunnerTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "project"
        self.cache = Path(temporary.name) / "cache"
        shutil.copytree(Path(__file__).with_name("example"), self.project, ignore=shutil.ignore_patterns(".runweave-cache"))
        self.payload = json.loads((self.project / "pipeline.json").read_text(encoding="utf-8"))

    def execute(self):
        return run(self.project, self.payload, self.cache)

    def test_selective_cache_reuse(self):
        first = self.execute()
        self.assertFalse(first["normalize"]["cached"])
        self.assertTrue(all(result["cached"] for result in self.execute().values()))
        (self.project / "report.py").write_text(
            (self.project / "report.py").read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8"
        )
        changed = self.execute()
        self.assertTrue(changed["normalize"]["cached"])
        self.assertFalse(changed["report"]["cached"])
        output = changed["report"]["directory"] / "files" / "summary.json"
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"tainan": 5, "taipei": 16})

    def test_tampered_artifact_fails_verification(self):
        first = self.execute()
        output = first["normalize"]["directory"] / "files" / "normalized.csv"
        output.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "cache verification failed"):
            self.execute()

    def test_failed_command_leaves_no_cache_entry(self):
        self.payload["steps"]["normalize"]["command"] = ["{python}", "-c", "raise SystemExit(7)"]
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute()
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_rejects_cycles_and_path_traversal(self):
        self.payload["steps"]["normalize"]["deps"] = ["report"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            plan(self.payload)
        self.payload["steps"]["normalize"]["outputs"] = ["../result"]
        with self.assertRaisesRegex(ValueError, "relative"):
            plan(self.payload)
