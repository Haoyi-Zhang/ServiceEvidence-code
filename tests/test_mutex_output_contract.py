"""Benign checks for the fresh CI mutex output and retained-cohort boundary."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scientific-checks.yml"


class MutexOutputContractTests(unittest.TestCase):
    def test_workflow_uses_one_attempt_scoped_fresh_path_and_retains_its_raw_files(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('out="$RUNNER_TEMP/p024-mutex-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"', workflow)
        self.assertIn('if [[ -e "$out" ]]; then', workflow)
        self.assertIn("printf 'MUTEX_OUT=%s\\n' \"$out\" >> \"$GITHUB_ENV\"", workflow)
        self.assertIn('experiments/mutex_campaign.py --out "$MUTEX_OUT"', workflow)
        self.assertIn('scripts/verify_mutex.py --out "$MUTEX_OUT"', workflow)
        self.assertIn('if [[ -n "${MUTEX_OUT:-}" && -d "$MUTEX_OUT" ]]; then', workflow)
        self.assertIn('cp -a "$MUTEX_OUT/." .scientific-results/run-outputs/fresh-mutex/', workflow)
        self.assertIn("cp -a results/. .scientific-results/retained/", workflow)
        self.assertIn("find results -type f -newer .scientific-results/run-start", workflow)
        self.assertIn("test_mutex_output_contract.py -v", workflow)

    @staticmethod
    def command(script, out):
        flags = ["-B"]
        if sys.flags.optimize:
            flags.append("-O")
        return subprocess.run(
            [sys.executable, *flags, str(ROOT / script), "--out", str(out)],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_campaign_rejects_existing_directory_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "retained"
            out.mkdir()
            marker = out / "original-record.txt"
            marker.write_bytes(b"unchanged scientific record\n")
            completed = self.command("experiments/mutex_campaign.py", out)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("fresh output directory required", completed.stderr)
            self.assertEqual(marker.read_bytes(), b"unchanged scientific record\n")
            self.assertEqual(sorted(path.name for path in out.iterdir()), [marker.name])

    def test_verifier_reads_explicit_path_not_retained_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "absent"
            completed = self.command("scripts/verify_mutex.py", out)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(out.parent.name, completed.stderr)
            self.assertIn("absent", completed.stderr)
            self.assertIn("checks.json", completed.stderr)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
