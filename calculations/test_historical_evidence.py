"""Offline regressions for the documented historical-source and observation readers."""

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calculations.historical_evidence import (
    BOUNDARY_RECORD, E05_RUN, e05_source_identities, read_observation, write_reproduction,
)


class HistoricalEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        config = ROOT / "experiments" / "runs" / E05_RUN / "config.json"
        self.config = json.loads(config.read_bytes())

    def copy_sources(self):
        archive = Path("analysis", "historical-sources", E05_RUN)
        shutil.copytree(ROOT / archive, self.root / archive)
        return self.root / archive

    def test_snapshot_is_independent_of_runtime(self):
        archive = self.copy_sources()
        checked = e05_source_identities(self.root, self.config)
        self.assertEqual(set(checked), set(self.config["design"]["source_sha256"]))
        self.assertEqual(len(checked), 14)
        self.assertTrue(all(item["match_mode"] == "raw" for item in checked.values()))
        self.assertEqual(len(list(archive.glob("*.py"))), 0)

    def test_changed_snapshot_is_not_replaced_by_current_file(self):
        archive = self.copy_sources()
        (archive / "budget.py.txt").write_bytes(b"modified evidence")
        with self.assertRaisesRegex(ValueError, "Historical E05 source digest mismatch"):
            e05_source_identities(self.root, self.config)

    def test_removed_source_in_config_is_rejected(self):
        del self.config["design"]["source_sha256"]["trace.py"]
        with self.assertRaisesRegex(ValueError, "source digest list"):
            e05_source_identities(self.root, self.config)

    def test_observation_is_verified_as_archived_data(self):
        source = ROOT / BOUNDARY_RECORD
        local = self.root / BOUNDARY_RECORD
        local.parent.mkdir(parents=True)
        shutil.copyfile(source, local)
        self.assertEqual(read_observation(self.root, BOUNDARY_RECORD), json.loads(source.read_bytes()))
        local.write_bytes(local.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "Historical audit digest mismatch"):
            read_observation(self.root, BOUNDARY_RECORD)

    def test_fresh_report_and_existing_alternate_file(self):
        default = self.root / "derived.json"
        existing = self.root / "existing.json"
        existing.write_bytes(b"retain")
        with self.assertRaises(FileExistsError):
            write_reproduction({"value": 1}, default, existing)
        self.assertEqual(existing.read_bytes(), b"retain")
        write_reproduction({"value": 2}, default, None)
        write_reproduction({"value": 3}, default, None)
        self.assertEqual(json.loads(default.read_bytes()), {"value": 3})


if __name__ == "__main__":
    unittest.main()
