import csv
import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from calculations import aflow_archive


def csv_bytes(rows):
    dest = io.StringIO(newline="")
    csv.writer(dest).writerows(rows)
    return dest.getvalue().encode()


class AFlowArchiveTest(unittest.TestCase):
    def test_test_csvs_and_validation_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores.tar.gz"
            with tarfile.open(path, "w:gz") as bundle:
                for dataset in aflow_archive.PAPER_SCORES:
                    for run in range(3):
                        columns = ["inputs"] if dataset == "DROP" else ["question"]
                        if dataset == "HotpotQA":
                            columns.append("context")
                        fields = ["item"] * len(columns)
                        if dataset in aflow_archive.ANSWER_DATASETS:
                            columns.extend(["expected_output", "prediction"])
                            fields.extend(["7", "7"])
                        header = columns + ["score", "cost"]
                        rows = [header, fields + ["0", "5"], fields + ["1", "3"]]
                        if dataset == "HumanEval" and run == 1:
                            rows.insert(0, ["0.98"])
                        if dataset == "MATH" and run == 1:
                            rows = [header, fields + ["1", "3"]]
                        data = csv_bytes(rows)
                        members = [f"results/{dataset}/graphs_test/round_5/run{run}.csv"]
                        if dataset == "MATH" and run == 1:
                            members.append(aflow_archive.MATH_VALIDATION)
                        for name in members:
                            member = tarfile.TarInfo(name)
                            member.size = len(data)
                            bundle.addfile(member, io.BytesIO(data))

            with patch.object(aflow_archive, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()):
                archive = aflow_archive.read_archive(path)
                result = archive["benchmarks"]
            self.assertEqual(archive["answer_score_check"]["rows"], 18)
            self.assertEqual(archive["answer_score_check"]["matching_rows"], 9)
            self.assertNotIn("answer_score_check", result["MBPP"]["files"][0])
            self.assertFalse(result["MATH"]["same_questions"])
            self.assertIsNone(result["MATH"]["archived_three_run_mean_percent"])
            self.assertEqual(len(result["MATH"]["also_in_math_validation"]), 1)
            self.assertEqual(result["HumanEval"]["archived_three_run_mean_percent"], "50.0")
            self.assertEqual(result["HumanEval"]["mean_of_run_max_costs"], "5")
            self.assertEqual([f["rows"] for f in result["HumanEval"]["files"]], [2, 2, 2])

    def test_drop_reorders_alternatives_and_preserves_token_counts(self):
        header = ["inputs", "expected_output", "prediction", "score", "cost"]
        rows = [
            ["long\ninput", "the Blue Fox | red bird", "wrong | RED BIRD!", "1", "0"],
            ["other", "red red fox", "red fox fox", "0.666666666667", "0"],
            ["duplicate", "fox", "FOX|a fox|", "1", "0"],
            ["disjoint", "dog", "fox", "0.000000000002", "0"],
        ]
        check = aflow_archive.score_file(csv_bytes([header] + rows), "DROP")["answer_score_check"]
        self.assertEqual(check["matching_rows"], 3)
        self.assertEqual(check["multiple_prediction_full_credit_csv_records"], [2])
        self.assertEqual(check["mismatch_csv_records"], [5])
        self.assertEqual(check["absolute_tolerance"], 1e-12)

    def test_gsm8k_uses_last_number_and_hotpot_scores_the_full_prediction(self):
        header = ["question", "expected_output", "prediction", "score", "cost"]
        rows = [
            ["a", "-1234.5", "Earlier 81. Last -1,234.50", "1", "0"],
            ["b", "0", "0.000001", "1", "0"],
            ["c", "0", "+0.000002", "0", "0"],
            ["d", "0", "no number", "0", "0"],
        ]
        numeric = aflow_archive.score_file(csv_bytes([header] + rows), "GSM8K")["answer_score_check"]
        self.assertEqual(numeric["matching_rows"], len(rows))
        answer = [["question", "context", "expected_output", "prediction", "score", "cost"],
                  ["a", "context", "the owl", "owl | fox", "0.666666666667", "0"]]
        hotpot = aflow_archive.score_file(csv_bytes(answer), "HotpotQA")["answer_score_check"]
        self.assertEqual(hotpot["matching_rows"], 1)
        self.assertNotIn("multiple_prediction_full_credit_csv_records", hotpot)

    def test_metadata_and_question_order_do_not_change_task_identity(self):
        rows = [["question", "score", "cost"], ["x\n", "0", "1"], ["y", "1", "3"]]
        score = aflow_archive.score_file(csv_bytes(rows), "HumanEval")
        reordered = [rows[0], [" y ", "0", "9"], ["x\r\n", "1", "7"]]
        other = aflow_archive.score_file(csv_bytes(reordered), "HumanEval")
        self.assertEqual(score["question_multiset_sha256"], other["question_multiset_sha256"])
        repeated = aflow_archive.score_file(csv_bytes(reordered + [reordered[1]]), "HumanEval")
        self.assertNotEqual(other["question_multiset_sha256"], repeated["question_multiset_sha256"])

    def test_other_archive_is_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "other"
            path.write_bytes(b"different release")
            with self.assertRaisesRegex(ValueError, "differs"):
                aflow_archive.read_archive(path)
