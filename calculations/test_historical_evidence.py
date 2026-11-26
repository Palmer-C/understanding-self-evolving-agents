"""Offline regressions for the documented historical-source and observation readers."""

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calculations.historical_evidence import (
    BOUNDARY_RECORD, E05_RUN, e05_source_identities, e05_trace_path, read_observation, write_reproduction,
)
from calculations.e01_prompt_exposure import HEADER, INDEX_FILE, original_trace_matches, prompt_exposure, prompt_lessons


class E01PromptTest(unittest.TestCase):
    def test_reader_requires_its_published_sealed_trace(self):
        run_path = Path("experiments/runs/E01-20260923T152230Z-90acda")
        trace_dir = Path("traces/grid4")
        sample = trace_dir / "sealed/classstate-07-r0/trace.json"
        source = ROOT / run_path
        summary = json.loads((source / "summary.json").read_bytes())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = root / run_path
            (root / INDEX_FILE).parent.mkdir(parents=True)
            shutil.copyfile(ROOT / INDEX_FILE, root / INDEX_FILE)
            shutil.copytree(source / trace_dir / "train", run / trace_dir / "train")
            (run / sample).parent.mkdir(parents=True)
            shutil.copyfile(source / sample, run / sample)

            report = prompt_exposure(root, run, summary)
            self.assertEqual((report["sealed_prompts"], report["sealed_originals_checked"]), (80, 1))
            (run / sample).unlink()
            with self.assertRaises(FileNotFoundError) as error:
                prompt_exposure(root, run, summary)
            self.assertEqual(Path(error.exception.filename), run / sample)

    def test_only_initial_system_prompt_counts(self):
        trace = {"task_id": "example", "verdict": False, "steps": [
            {"kind": "system", "content": "base" + HEADER + "- second\n- first\n"},
            {"kind": "assistant", "content": "- second\n"},
        ]}
        lines = {"- first": 0, "- second": 1}
        self.assertEqual(prompt_lessons(trace, "example", False, lines), [1, 0])
        with self.assertRaises(ValueError):
            prompt_lessons(trace, "example", None, lines)
        trace["steps"][0]["content"] = "base"
        self.assertEqual(prompt_lessons(trace, "example", False, lines), [])
        trace["steps"][0]["content"] += HEADER + "- unknown\n"
        with self.assertRaises(ValueError):
            prompt_lessons(trace, "example", False, lines)

    def test_git_checkout_line_endings(self):
        archived = b'{\r\n  "value": true\r\n}\r\n'
        expected = hashlib.sha256(archived).hexdigest()
        self.assertTrue(original_trace_matches(archived, expected))
        self.assertTrue(original_trace_matches(archived.replace(b"\r\n", b"\n"), expected))
        self.assertFalse(original_trace_matches(archived.replace(b"true", b"false"), expected))
        self.assertFalse(original_trace_matches(archived.replace(b"\r\n", b"\n", 1), expected))


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

    def test_e05_trace_paths_on_native_and_posix_filesystems(self):
        sequences = ROOT / 'experiments' / 'runs' / E05_RUN / 'sequences'
        # ZIP paths are POSIX-style even when unittest runs on Windows.
        with zipfile.ZipFile(self.root / 'traces.zip', 'w') as archive:
            for trace in sequences.glob('*/*/trace.json'):
                archive.writestr(trace.relative_to(sequences).as_posix(), trace.read_bytes())
            seen = 0
            for complete in sorted(sequences.glob('*/complete.json')):
                zip_sequence = zipfile.Path(archive) / complete.parent.name
                for event in json.loads(complete.read_bytes())['events']:
                    original = event['trace']
                    normalized = PureWindowsPath(original).as_posix()
                    self.assertNotEqual(original, normalized)
                    self.assertIn('/', normalized)
                    posix_parts = PurePosixPath(normalized).parts
                    self.assertEqual(len(posix_parts), 2)
                    expected = complete.parent.joinpath(*posix_parts).read_bytes()
                    for recorded in (original, normalized):
                        self.assertEqual(e05_trace_path(complete.parent, recorded).read_bytes(), expected)
                        self.assertEqual(e05_trace_path(zip_sequence, recorded).read_bytes(), expected)
                    seen += 1
            self.assertEqual(seen, 9)

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
