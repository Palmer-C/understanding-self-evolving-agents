"""Data-only regression tests for historical training order and trigger report export."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from . import trigger_signals as signals


class TriggerReplayTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.train = self.run / "traces/arm/train"

    def record(self, directory, task, verdict):
        path = self.train / directory / "trace.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"task_id": task, "verdict": verdict}), encoding="utf-8")
        return path

    def test_numbered_order_survives_task_repetition_and_double_digits(self):
        for i in reversed(range(12)):
            task = "z-one" if i % 2 == 0 else "a"
            self.record(f"{task}-e{i}", task, bool(i % 2))
        rows = signals.load_train_episodes(self.run, "arm")
        self.assertEqual([r["verdict"] for r in rows], [False, True] * 6)
        result = signals.analyze(self.run, "arm", ["text"] * len(rows))
        self.assertEqual(result["error_run"]["n_ge2"], 0)
        self.assertEqual(result["drift"]["max"], 0.0)

    def test_duplicate_gap_unknown_or_incomplete_trace_is_rejected(self):
        self.record("x-e00", "x", False)
        (self.train/"notes").mkdir()
        self.assertEqual(len(signals.load_train_episodes(self.run,"arm")), 1)
        for directory, label in (("y-e0","重复"), ("y-e2","连续"), ("y-1","编号")):
            with self.subTest(directory=directory):
                path = self.record(directory, "y", False)
                with self.assertRaisesRegex(ValueError, label):
                    signals.load_train_episodes(self.run, "arm")
                path.unlink()
                path.parent.rmdir()
        (self.train/"y-e1").mkdir()
        with self.assertRaisesRegex(ValueError, "trace.json"):
            signals.load_train_episodes(self.run, "arm")

    def test_verdict_requires_an_actual_boolean_and_task_must_match(self):
        trace = self.record("x-e0","x",True)
        for fields in ({}, {"verdict":None}, {"verdict":0}, {"verdict":"false"},
                       {"verdict":True,"task_id":"y"}):
            with self.subTest(fields=fields):
                trace.write_text(json.dumps({"task_id":"x", **fields}), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "任务号或布尔判定"):
                    signals.load_train_episodes(self.run, "arm")
        trace.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "任务号或布尔判定"):
            signals.load_train_episodes(self.run, "arm")

    def test_candidate_alignment_and_missing_measurements(self):
        self.record("z-e0","z",False)
        self.record("a-e1","a",True)
        entries = [{"index":0,"source_task":"z","source_verdict":False,"text":"alpha"},
                   {"index":1,"source_task":"a","source_verdict":True,"text":"bravo"}]
        score = signals.analyze(self.run, "arm", entries)
        self.assertEqual(score, signals.analyze(self.run, "arm", ["alpha","bravo"]))
        self.assertEqual(score["gating"]["n_writes_total"], 2)
        outcomes = signals.analyze(self.run, "arm", [])
        self.assertIsNone(outcomes["novelty"])
        self.assertIsNone(outcomes["gating"])
        self.assertEqual(outcomes["error_run"], score["error_run"])
        for changed in (["one"], ["one","two","three"], ["one"," "], entries[::-1], [entries[0],"two"],
                        [dict(entries[0],source_verdict=0),entries[1]]):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                signals.analyze(self.run, "arm", changed)

    def test_cli_prints_by_default_and_publishes_only_into_a_new_directory(self):
        self.record("t-e0","t",False)
        item={"index":0,"source_task":"t","source_verdict":False,"text":"word frequency"}
        dest=self.root/"reports"
        sentinel=self.root/"kept.json"
        sentinel.write_bytes(b"preserve me")
        with patch.object(signals,"RUNS_ROOT",self.root), redirect_stderr(io.StringIO()):
            for key in ("arm_lessons", "arm"):
                (self.run/"summary.json").write_text(json.dumps({"memory":{key:[item]}}),encoding="utf-8")
                before=set(self.root.rglob("*"))
                with redirect_stdout(io.StringIO()) as stream:
                    self.assertEqual(signals.main(["--run","run"]),0)
                self.assertIn("1/1",stream.getvalue())
                self.assertEqual(before,set(self.root.rglob("*")))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(signals.main(["--run","run","--output-dir",str(dest)]),0)
            self.assertEqual(sorted(p.suffix for p in dest.iterdir()), [".json",".md"])
            self.assertEqual(json.loads((dest/"triggers-run.json").read_bytes())["signals"][0]["n_episodes"],1)
            (dest/"triggers-run.md").write_bytes(b"original report")
            for existing in (dest,sentinel):
                with self.assertRaises(SystemExit):
                    signals.main(["--run","run","--output-dir",str(existing)])
            self.assertEqual((dest/"triggers-run.md").read_bytes(),b"original report")
            self.assertEqual(sentinel.read_bytes(),b"preserve me")

    def test_failed_second_write_and_competing_publishers(self):
        dest=self.root/"reports"
        report={"run_id":"run","signals":[]}
        write=Path.write_text
        def break_second(path, *args, **kwargs):
            if path.suffix==".md":
                raise OSError("simulated second write failure")
            return write(path,*args,**kwargs)
        with patch.object(Path,"write_text",break_second), self.assertRaises(OSError):
            signals.write_reports(dest,report,"markdown")
        self.assertEqual(list(self.root.iterdir()), [])
        def publish(i):
            try:
                signals.write_reports(dest,dict(report,instance=i),str(i))
                return True
            except OSError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(publish,range(2))),[False,True])
        winner=json.loads((dest/"triggers-run.json").read_bytes())["instance"]
        self.assertEqual((dest/"triggers-run.md").read_text(encoding="utf-8"),str(winner))
        self.assertEqual(list(self.root.iterdir()),[dest])

    def test_fixed_e01_requires_the_grid4_lesson_archive(self):
        run_id = "E01-20260923T152230Z-90acda"
        source = signals.RUNS_ROOT / run_id
        run = self.root / run_id
        shutil.copytree(source / "traces/grid4/train", run / "traces/grid4/train")
        summary = run / "summary.json"
        original = (source / "summary.json").read_bytes()
        output = self.root / "reports"
        with patch.object(signals, "RUNS_ROOT", self.root):
            for change in ("missing field", "changed text"):
                data = json.loads(original)
                if change == "missing field":
                    del data["memory"]["grid4_lessons"]
                else:
                    data["memory"]["grid4_lessons"][0]["text"] += " changed"
                summary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                with self.subTest(change=change), redirect_stderr(io.StringIO()) as error:
                    with self.assertRaises(SystemExit) as raised:
                        signals.main(["--run", run_id, "--output-dir", str(output)])
                    self.assertNotEqual(raised.exception.code, 0)
                    self.assertIn("SHA-256", error.getvalue())
                    self.assertIn(str(summary), error.getvalue())
                    self.assertFalse(output.exists())
            summary.write_bytes(original)
            with redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(signals.main(["--run", run_id]), 0)
            self.assertIn("| grid4 | 8 |", stream.getvalue())
            self.assertIn("| 8/8 |", stream.getvalue())
            (run / "traces/grid4").rename(run / "traces/other-arm")
            with redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit):
                signals.main(["--run", run_id])
            self.assertIn("traces/grid4/train", error.getvalue())

    def test_custom_e01_can_report_verdicts_without_lessons(self):
        run_id = "E01-private"
        run = self.root / run_id
        self.train = run / "traces/grid4/train"
        self.record("task-e0", "task", False)
        (run / "summary.json").write_text("{}", encoding="utf-8")
        with patch.object(signals, "RUNS_ROOT", self.root), redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(signals.main(["--run", run_id]), 0)
        self.assertIn("| grid4 | 1 | 1.0000", stream.getvalue())
        self.assertIn("无经验文本", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
