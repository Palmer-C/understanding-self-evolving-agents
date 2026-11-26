"""Run book/build.ps1 with a controlled compiler to exercise Windows PDF delivery."""
import itertools
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == "nt", "Tests Windows PDF replacement and sharing rules")
class BookPublicationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.book = self.root / "book"
        self.book.mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[1] / "book/build.ps1",
                        self.book / "build.ps1")
        self.latexmk = self.root / "latexmk.cmd"
        self.latexmk.write_text(
            '@echo off\ncopy /b /y "%~dp0candidate.pdf" "build\\main.pdf" >nul\n'
            'echo final pass>build\\main.log\nexit /b 0\n', encoding="ascii")
        # Keep the publication fixtures independent of a system TeX installation.
        self.maps = {"cmex10": "omx.cmap", "msbm10": "umsb.cmap"}
        for name in self.maps.values():
            (self.root / name).write_bytes(("test map " + name).encode("ascii"))
        (self.root / "kpsewhich.cmd").write_text(
            '@echo off\nfor %%i in (%*) do set "map=%%~i"\n'
            'if not exist "%~dp0%map%" exit /b 1\necho %~dp0%map%\n', encoding="ascii")
        self.tool_env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ["PATH"])
        self.outdir = self.book / "build"
        self.outputs = [self.outdir / "main.pdf", self.book / "main.pdf"]

    def build(self, payload):
        (self.root / "candidate.pdf").write_bytes(payload)
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                               "-File", self.book / "build.ps1", "-BuildRoot", self.root / "tmp",
                               "-Latexmk", self.latexmk], capture_output=True, timeout=45, env=self.tool_env)

    def status(self):
        return dict(row.split("=", 1) for row in
                    (self.outdir / "build-status.txt").read_text(encoding="utf-8-sig").splitlines())

    def test_math_maps_are_loaded_in_the_build_copy(self):
        self.assertEqual(self.build(b"first").returncode, 0)
        work, = (self.root / "tmp").glob("seab-build-*")
        for font, name in self.maps.items():
            self.assertEqual((work / font).read_bytes(), (self.root / name).read_bytes())
            self.assertFalse((self.book / font).exists())

        (self.root / "umsb.cmap").unlink()
        result = self.build(b"second")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"umsb.cmap (font msbm10)", result.stderr)
        self.assertEqual(self.status()["pdf"], "False")
        self.assertEqual([p.read_bytes() for p in self.outputs], [b"first", b"first"])

    def test_authored_file_named_for_a_math_font_is_preserved(self):
        self.assertEqual(self.build(b"previous").returncode, 0)
        authored = self.book / "cmex10"
        authored.write_bytes(b"authored resource")
        result = self.build(b"candidate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"cmex10", result.stderr)
        self.assertEqual(authored.read_bytes(), b"authored resource")
        self.assertEqual(self.status()["pdf"], "False")
        self.assertEqual([p.read_bytes() for p in self.outputs], [b"previous", b"previous"])

    def test_old_outputs_survive_failure_and_retry_succeeds(self):
        old, new = b"previous fixture", b"current fixture"
        self.assertEqual(self.build(old).returncode, 0)
        self.assertEqual([p.read_bytes() for p in self.outputs], [old, old])
        for path in self.outputs:
            with self.subTest(locked=path.parent.name):
                with path.open("rb"):
                    result = self.build(new)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"PDF publication failed", result.stderr)
                self.assertEqual(self.status()["exit"], str(result.returncode))
                self.assertEqual(self.status()["pdf"], "False")
                self.assertEqual([p.read_bytes() for p in self.outputs], [old, old])
                self.assertFalse(list(self.outdir.glob("publish-*")))
        self.assertEqual(self.build(new).returncode, 0)
        self.assertEqual([p.read_bytes() for p in self.outputs], [new, new])
        self.assertEqual(self.status(), {"exit": "0", "pdf": "True", "undef": "0", "errors": "0"})

    def test_first_publication_cannot_leave_one_new_output(self):
        self.outputs[1].write_bytes(b"old reader copy")
        with self.outputs[1].open("rb"):
            self.assertNotEqual(self.build(b"candidate").returncode, 0)
        self.assertFalse(self.outputs[0].exists())
        self.assertEqual(self.outputs[1].read_bytes(), b"old reader copy")
        self.assertEqual(self.status()["pdf"], "False")

    def test_busy_publisher_does_not_replace_its_outputs_or_status(self):
        self.assertEqual(self.build(b"one").returncode, 0)
        status_before = (self.outdir / "build-status.txt").read_bytes()
        with (self.outdir / ".publish.lock").open("rb"):
            self.assertNotEqual(self.build(b"two").returncode, 0)
        self.assertEqual([p.read_bytes() for p in self.outputs], [b"one", b"one"])
        self.assertEqual((self.outdir / "build-status.txt").read_bytes(), status_before)

    def test_wrong_installed_bytes_restore_both_outputs(self):
        # Change only the disposable copy, immediately before it measures a destination.
        # Each case exercises the real file replacement, hashing, and rollback code.
        script = self.book / "build.ps1"
        original = script.read_text(encoding="utf-8-sig")
        anchor = "function Get-PdfSha256($path) {"
        self.assertEqual(original.count(anchor), 1)
        self.outdir.mkdir()
        for target, old_build, old_reader in itertools.product(
                self.outputs, (False, True), (False, True)):
            with self.subTest(target=target, old_build=old_build, old_reader=old_reader):
                before = [b"old build" if old_build else None, b"old reader" if old_reader else None]
                for path, payload in zip(self.outputs, before):
                    if payload is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(payload)
                quoted = str(target).replace("'", "''")
                inject = f"if ($path -eq '{quoted}') {{ [IO.File]::WriteAllText($path, 'incorrect copy') }}"
                script.write_text(original.replace(anchor, anchor + "\n    " + inject), encoding="utf-8-sig")
                result = self.build(b"current candidate")
                self.assertEqual(result.returncode, 1)
                self.assertIn(b"PDF SHA-256 mismatch", result.stderr)
                self.assertEqual(self.status(), {"exit": "1", "pdf": "False", "undef": "0", "errors": "0"})
                after = [path.read_bytes() if path.exists() else None for path in self.outputs]
                self.assertEqual(after, before)
                self.assertFalse(list(self.outdir.glob("publish-*")))


if __name__ == "__main__":
    unittest.main()
