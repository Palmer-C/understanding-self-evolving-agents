"""Exit-code contract for the cross-reference report and its opt-in strict mode."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class CrossrefExitTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "tools").mkdir()
        self.chapters = self.root / "book/chapters"
        self.chapters.mkdir(parents=True)
        self.script = Path(shutil.copyfile(Path(__file__).with_name("check_crossref.py"),
                                           self.root / "tools/check_crossref.py"))

    def check(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", str(self.script), *args],
                              capture_output=True, encoding="utf-8", cwd=self.root, timeout=10)

    def test_dangling_reference_fails_strict_and_preserves_report(self):
        (self.chapters / "a.tex").write_text(r"\ref{not-defined}", encoding="utf-8")
        normal = self.check()
        report = self.root / "report.txt"
        strict = self.check("--strict", "--out", str(report))
        self.assertEqual((normal.returncode, strict.returncode), (0, 1))
        self.assertEqual(strict.stdout, normal.stdout)
        self.assertEqual(strict.stdout, report.read_text(encoding="utf-8"))
        self.assertIn("A 未定义引用=1", strict.stdout)

    def test_duplicate_definitions_fail_strict(self):
        for name in ("a.tex", "b.tex"):
            (self.chapters / name).write_text(r"\label{shared}", encoding="utf-8")
        strict = self.check("--strict")
        self.assertEqual(strict.returncode, 1)
        self.assertIn("B 重复标签=1", strict.stdout)
        self.assertEqual(self.check().returncode, 0)

    def test_float_warnings_and_orphan_labels_stay_advisory(self):
        (self.chapters / "a.tex").write_text(r"\begin{figure}\end{figure}\ref{b}\label{orphan}",
                                             encoding="utf-8")
        (self.chapters / "b.tex").write_text(r"\label{b}", encoding="utf-8")
        strict = self.check("--strict")
        self.assertEqual(strict.returncode, 0)
        self.assertIn("D 缺caption=1 / 缺label=1", strict.stdout)
        self.assertIn("E 孤立标签=1", strict.stdout)

    def test_empty_input_is_distinct_from_a_successful_strict_scan(self):
        self.assertEqual(self.check().returncode, 0)
        self.assertEqual(self.check("--strict").returncode, 2)


if __name__ == "__main__":
    unittest.main()
