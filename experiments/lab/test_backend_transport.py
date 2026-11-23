"""Offline regression tests for backend configuration, transport, and E01 entry points."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock, patch

from experiments.lab import backends, check_backend, run_e01


class TransportTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.local = stack.enter_context(patch.object(backends, "_local_backend_settings", return_value={}))
        self.transport = stack.enter_context(patch.object(backends.urllib.request, "build_opener")).return_value

    def test_specific_credential_destination(self):
        self.local.return_value = {
            "AGENT_LAB_API_KEY": "example", "AGENT_LAB_MODEL": "demo",
            "AGENT_LAB_BASE_URL": "https://example.invalid/v1",
        }
        with patch.dict(os.environ, {"AGENT_LAB_BASE_URL": "https://other.invalid"}):
            with self.assertRaises(backends.BackendUnavailable):
                backends.OpenAIChatBackend()
        with self.assertRaises(backends.BackendUnavailable):
            backends.OpenAIChatBackend(base_url="https://example.invalid:444")
        backend = backends.OpenAIChatBackend(base_url="https://example.invalid:443/v2")
        self.assertEqual(backend.base_url, "https://example.invalid/v2")
        self.assertNotIn("AGENT_LAB_API_KEY", os.environ)
        self.transport.open.assert_not_called()

    def test_ambient_key_does_not_follow_a_local_base(self):
        self.local.return_value = {"AGENT_LAB_BASE_URL": "https://example.invalid"}
        with patch.dict(os.environ, {"AGENT_LAB_API_KEY": "example"}):
            with self.assertRaises(backends.BackendUnavailable):
                backends.OpenAIChatBackend(model="demo")

    def test_invalid_addresses_and_headers_fail_before_request(self):
        for uri in ["http://example.invalid", "https://name@example.invalid",
                    "https://example.invalid/v1?token=example", "https://example.invalid/#x",
                    "https://example.invalid:bad", "https://example.invalid/has space"]:
            with self.subTest(uri=uri), self.assertRaises(backends.BackendUnavailable):
                backends.OpenAIChatBackend(model="demo", api_key="example", base_url=uri)
        with self.assertRaises(backends.BackendUnavailable):
            backends.OpenAIChatBackend(model="demo", api_key="two words")
        self.transport.open.assert_not_called()

    def test_mock_reply_updates_usage_and_pins_destination(self):
        backend = backends.OpenAIChatBackend(model="demo", api_key="example", base_url="https://example.invalid/v1")
        raw = {"choices": [{"message": {"content": "ok"}}],
               "usage": {"prompt_tokens": 3, "completion_tokens": 1}}
        self.transport.open.return_value.__enter__.return_value.read.return_value = json.dumps(raw).encode()
        backend.base_url = "https://other.invalid"
        reply = backend.generate([])
        request, = self.transport.open.call_args.args
        self.assertEqual(request.full_url, "https://example.invalid/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer example")
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual((reply.text, reply.prompt_tokens, reply.completion_tokens), ("ok", 3, 1))
        handler, = backends.urllib.request.build_opener.call_args.args
        self.assertIsInstance(handler, backends._NoModelRedirects)
        self.assertIsNone(handler.redirect_request(None, None, 302, "redirect", {}, "https://example.invalid/next"))

    def test_http_error_status_only(self):
        backend = backends.OpenAIChatBackend(model="demo", api_key="example")
        self.transport.open.side_effect = urllib.error.HTTPError(
            backend.base_url, 401, "detail", {}, io.BytesIO(b"private response detail")
        )
        with self.assertRaisesRegex(backends.BackendUnavailable, "HTTP 401") as caught:
            backend.generate([])
        self.assertNotIn("detail", str(caught.exception))
        self.assertEqual(backend.retries, 0)


class EntryPointTests(unittest.TestCase):
    def test_import_and_scripted_use_preserve_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copyfile(backends.__file__, root / "backends.py")
            # Invalid UTF-8 makes an unintended read fail without inspecting real credentials.
            (root / ".env").write_bytes(b"\xff")
            proc = subprocess.run([sys.executable, "-B", "-c",
                                   "import backends; backends.build_backend('scripted', replies=['ok']).generate([])"],
                                  cwd=root, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_e01_offline_and_unavailable_execution_never_open_backend(self):
        with patch.object(run_e01, "build_backend") as constructor, \
                patch.object(run_e01, "load_tasks") as tasks, patch.object(run_e01, "new_run_id") as run_id, \
                contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_e01.main([]), 0)
            self.assertEqual(run_e01.main(["--trial"]), 0)
            self.assertIn("每格训练 2 个回合", stdout.getvalue())
            with patch.object(run_e01, "require_isolated_execution", side_effect=run_e01.ExecutionUnavailable("隔离执行器未就绪")), \
                    self.assertRaises(SystemExit) as exc:
                run_e01.main(["--trial", "--execute-real"])
            self.assertEqual(exc.exception.code, 2)
            constructor.assert_not_called()
            tasks.assert_not_called()
            run_id.assert_not_called()

    def test_e01_library_phases_refuse_live_backend_before_adaptation(self):
        backend = Mock()
        backend.name = "openai-chat"
        task = Mock()
        with tempfile.TemporaryDirectory() as temp, patch.object(run_e01, "adapt_note") as adaptation:
            out = Path(temp) / "preview"
            with self.assertRaises(run_e01.ExecutionUnavailable):
                run_e01.train_phase("grid3", backend, [task], 1, out)
            with self.assertRaises(run_e01.ExecutionUnavailable):
                run_e01.sealed_phase("grid3", backend, [task], 1, [], out, None, 42)
            adaptation.assert_not_called()
            backend.generate.assert_not_called()
            self.assertFalse(out.exists())

    def test_backend_probe_is_explicit(self):
        backend = Mock(model="fixture", base_url="https://example.invalid")
        with patch.object(check_backend, "OpenAIChatBackend", return_value=backend), \
                contextlib.redirect_stdout(io.StringIO()):
            for argv in ([], ["--no-probe"]):
                self.assertEqual(check_backend.main(argv), 0)
                backend.generate.assert_not_called()
            backend.generate.return_value.text = "ok"
            self.assertEqual(check_backend.main(["--probe"]), 0)
            backend.generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
