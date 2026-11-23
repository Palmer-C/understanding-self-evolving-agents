import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from calculations import redraw_quantitative_figures as figures


class FigureDataTests(unittest.TestCase):
    def test_five_archived_task_level_intervals_in_percentage_points(self):
        expected = [(-21.25, -10.0, 1.25), (-26.25, -11.25, 5.0),
                    (-23.75, -10.0, 2.5), (-38.75, -20.0, -2.5),
                    (-31.25, -15.0, 1.25)]
        actual = figures.effect_rows(figures.ROOT)
        self.assertEqual(len(expected), len(actual))
        for row, reference in zip(actual, expected):
            for value, target in zip(row, reference):
                self.assertAlmostEqual(value, target)

    def test_integer_break_even_points_and_maintenance_charge(self):
        rows = figures.cost_rows(figures.ROOT)
        self.assertEqual([k for k, base, fixed, _ in rows if base == fixed], [4])
        self.assertEqual([k for k, base, _, maintained in rows if base == maintained], [4, 8])
        self.assertEqual(rows[6], (6, 30, 24, 36))

    def test_mismatched_archived_costs_are_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = json.loads((figures.ROOT / figures.COST_INPUT).read_text(encoding="utf-8-sig"))
            source["maintained_skill"][6] += 1
            copy = root / figures.COST_INPUT
            copy.parent.mkdir()
            copy.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "公式"):
                figures.cost_rows(root)

    def test_existing_directory_is_rejected_before_any_compilation(self):
        with TemporaryDirectory() as temp, patch.object(figures.subprocess, "run") as compile_pdf:
            directory = Path(temp)
            previous = directory / "ch04-e02-effects.pdf"
            previous.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                figures.render(directory)
            self.assertEqual(previous.read_bytes(), b"existing")
            compile_pdf.assert_not_called()

    def test_second_compilation_failure_leaves_no_partial_output(self):
        with TemporaryDirectory() as temp, patch.object(figures.shutil, "which", return_value="xelatex"):
            target = Path(temp) / "new"
            success = figures.subprocess.CompletedProcess([], 0, b"")
            failure = figures.subprocess.CompletedProcess([], 1, b"! Compilation failed.")
            with patch.object(figures.subprocess, "run", side_effect=[success, failure]):
                with self.assertRaisesRegex(RuntimeError, "ch08-cost"):
                    figures.render(target)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
