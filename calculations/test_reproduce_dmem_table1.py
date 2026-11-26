"""Small offline regressions for the reader's D-MEM Table 1 audit."""
from contextlib import redirect_stderr
import copy
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calculations import reproduce_dmem_table1 as audit


class Table1AuditTest(unittest.TestCase):
    def setUp(self):
        self.questions = [{"question": "How many?", "category": 1, "answer": 2}]
        self.questions += [{"question": f"Unanswerable {n}?", "category": 5,
                            "adversarial_answer": "blue"} for n in range(4)]
        self.locomo = [{"sample_id": "conv-26", "qa": self.questions}]

    def result(self, method, refused):
        rows = [{"question": "How many?", "category": 1, "reference": 2,
                 "prediction": "2", "metrics": {"f1": 1}}]
        for n, item in enumerate(self.questions[1:]):
            rows.append({"question": item["question"], "category": 5, "reference": "blue",
                         "prediction": "NOT MENTIONED" if n in refused else "Blue!",
                         "metrics": {"f1": int(n not in refused)}})
        return {"method": method, "results": list(reversed(rows))}

    def test_scores_pair_by_question_and_keep_the_two_rules_separate(self):
        first = self.result("A-MEM", {0, 1})
        second = self.result("D-MEM", {1, 2})
        second["results"].reverse()
        report = audit.table1_report(self.locomo, first, second)
        scores = report["scores_from_predictions"]["A-MEM"]
        self.assertEqual(scores["by_locomo_category"]["5"]["word_set_f1"], 0.5)
        self.assertEqual(scores["by_locomo_category"]["1"]["label"], "multi-hop")
        self.assertEqual(scores["category_5_official_phrase_hits"], 2)
        pairs = report["category_5_official_phrase_rule"]
        self.assertEqual([pairs[key] for key in ("both", "a_mem_only", "d_mem_only", "neither")],
                         [1, 1, 1, 1])
        self.assertEqual(audit.word_set_f1("BLUE blue? green.", "blue"), Fraction(2, 3))

    def test_missing_duplicate_changed_category_reference_and_score_are_refused(self):
        truth = audit.index_questions(self.questions)
        rows = self.result("A-MEM", {0})["results"]
        for field, value, error in (("category", 4, "category"), ("reference", "red", "reference"),
                                    ("metrics", {"f1": -1}, "word-set")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                changed = copy.deepcopy(rows)
                changed[0][field] = value
                audit.score_method(truth, changed)
        with self.assertRaisesRegex(ValueError, "questions differ"):
            audit.score_method(truth, rows[1:])
        with self.assertRaisesRegex(ValueError, "unique"):
            audit.score_method(truth, rows + [rows[0]])

    def test_cli_checks_bytes_and_never_replaces_an_existing_file(self):
        objects = {"LoCoMo": self.locomo, "A-MEM": self.result("A-MEM", {0}),
                   "D-MEM": self.result("D-MEM", {0, 1})}
        with tempfile.TemporaryDirectory() as directory:
            paths = {key: Path(directory, key + ".json") for key in objects}
            for key, path in paths.items():
                path.write_bytes(json.dumps(objects[key]).encode("utf-8"))
            checksums = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
            args = ["--locomo", str(paths["LoCoMo"]), "--a-mem", str(paths["A-MEM"]),
                    "--d-mem", str(paths["D-MEM"])]
            out = Path(directory, "report.json")
            with patch.dict(audit.SOURCE_SHA256, checksums), redirect_stderr(io.StringIO()):
                audit.main(args + ["--output", str(out)])
                self.assertEqual(json.loads(out.read_bytes())["category_5_official_phrase_rule"]["both"], 1)
                for existing in (out, paths["LoCoMo"]):
                    before = existing.read_bytes()
                    with self.assertRaises(SystemExit) as exc:
                        audit.main(args + ["--output", str(existing)])
                    self.assertNotEqual(exc.exception.code, 0)
                    self.assertEqual(existing.read_bytes(), before)
                paths["A-MEM"].write_bytes(paths["A-MEM"].read_bytes() + b"\n")
                with self.assertRaises(SystemExit) as exc:
                    audit.main(args + ["--output", str(out.with_suffix(".new.json"))])
                self.assertNotEqual(exc.exception.code, 0)
                self.assertFalse(out.with_suffix(".new.json").exists())


if __name__ == "__main__":
    unittest.main()
