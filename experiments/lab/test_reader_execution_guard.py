"""Offline checks for the public file tools and execution entry points."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from . import build_taskset, run_e05, run_e05_v2, run_e11_v2, run_e12_v2
from .protocol_agent_v3 import ProtocolAgentV3
from .sandbox import ExecutionUnavailable, Sandbox, SandboxViolation
from .static_agent import StaticAgent
from .tasks import LiteralFixtureTask, Task


class ReaderExecutionGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sandbox = Sandbox(self.root)

    def test_task_initialization_and_protected_paths(self):
        task = Task("lesson", "", {"src/note.txt": "A", "checks/key.txt": "B"},
                    protected=["checks/key.txt"])
        task.materialize(self.sandbox)
        self.assertEqual(self.sandbox.list_files(), ["checks/key.txt", "src/note.txt"])
        for name in ("CHECKS/Key.TXT", "src/Panel_TEST.py", "TEST_example.py", "Conftest.py"):
            with self.subTest(name=name), self.assertRaises(SandboxViolation):
                self.sandbox.write_file(name, "example")
        self.sandbox.write_file("src/note.txt", "C")
        self.assertEqual(self.sandbox.read_file("src/note.txt"), "C")
        self.assertEqual(self.sandbox.read_file("checks/key.txt"), "B")

    def test_inputs_require_relative_names_before_installing_files(self):
        for name in (str(self.root / "local.txt"), "./local.txt", "notes/../local.txt"):
            with self.subTest(name=name), self.assertRaises(SandboxViolation):
                Task("lesson", "", {"first.txt": "A", name: "B"}).materialize(self.sandbox)
        self.assertEqual(self.sandbox.list_files(), [])

    def test_cleanup_only_removes_owned_workspaces(self):
        self.sandbox.write_file("note.txt", "kept")
        self.sandbox.cleanup()
        self.assertEqual((self.root / "note.txt").read_text(), "kept")
        owned = Sandbox.create_temp("reader")
        owned.cleanup()
        self.assertFalse(owned.root.exists())

    def test_missing_executor_is_not_a_failing_verdict(self):
        with patch("subprocess.Popen") as launch, self.assertRaises(ExecutionUnavailable):
            Task("lesson", "").verify(self.sandbox)
        launch.assert_not_called()

    def test_fixture_verdict_requires_exact_text_and_discloses_method(self):
        task = LiteralFixtureTask("lesson", "", fixture_name="note.txt", fixture_text="done")
        with patch("subprocess.Popen") as launch:
            self.assertFalse(task.verify(self.sandbox).ok)
            self.sandbox.write_file("note.txt", "done.")
            self.assertFalse(task.verify(self.sandbox).ok)
            self.sandbox.write_file("note.txt", "done")
            result = task.verify(self.sandbox)
        self.assertTrue(result.ok)
        self.assertIn("固定样例文本比对", result.verdict_source)
        launch.assert_not_called()

    def test_direct_agents_stop_before_backend_or_materialization(self):
        backend = Mock()
        backend.name = "openai-chat"
        task = Mock(spec=Task)
        for agent in (StaticAgent(backend), ProtocolAgentV3(backend)):
            with self.subTest(agent=agent.agent_id), self.assertRaises(ExecutionUnavailable):
                agent.run_episode(task)
        backend.generate.assert_not_called()
        task.materialize.assert_not_called()

    def test_explicit_lab_run_stops_before_writing(self):
        destination = self.root / "tasks"
        with patch.object(build_taskset, "build_variant") as build:
            self.assert_execution_stopped(build_taskset.main, ["--out", str(destination), "--lab-run"])
        build.assert_not_called()
        self.assertFalse(destination.exists())

    def assert_execution_stopped(self, main, args):
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream), self.assertRaises(SystemExit) as raised:
            main(args)
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("隔离执行器", stream.getvalue())

    def test_taskset_defaults_to_spec_only(self):
        fixture = {"demo": {"variants": [{} for _ in range(8)]}}
        def row(family, index, spec, out):
            return {"task_id": f"demo-{index:02d}", "family": family, "split": "train"}
        for options in ([], ["--no-lab-run"]):
            with self.subTest(options=options), patch.object(build_taskset, "FAMILIES", fixture), \
                    patch.object(build_taskset, "build_variant", side_effect=row), \
                    patch.object(build_taskset, "lab_run") as live, contextlib.redirect_stdout(io.StringIO()) as log:
                self.assertEqual(build_taskset.main(["--out", str(self.root), *options]), 0)
                self.assertIn("lab_run = skipped", log.getvalue())
                self.assertTrue((self.root / "index.csv").is_file())
                live.assert_not_called()

    def test_legacy_and_v2_cli_stop_before_loading_or_spending(self):
        for module, args in ((run_e05, []), (run_e05_v2, ["--execute"])):
            with self.subTest(module=module.__name__), patch.object(module, "load_all_tasks") as load:
                self.assert_execution_stopped(module.main, args)
                load.assert_not_called()

    def test_matching_manifests_do_not_enable_execution(self):
        design = {"example": "approved"}
        manifest = self.root / "approved.json"
        manifest.write_text(json.dumps(design), encoding="utf-8")
        destination = self.root / "new-preflight.json"
        args = ["--execute", "--approved-manifest", str(manifest), "--save-preflight", str(destination)]
        for module, result in ((run_e11_v2, ([], design)), (run_e12_v2, design)):
            with self.subTest(module=module.__name__), patch.object(module, "preflight", return_value=result):
                self.assert_execution_stopped(module.main, args)
                self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
