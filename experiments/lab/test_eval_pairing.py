"""Constructed regressions for paired-input integrity. No model backend is used."""
import contextlib
import io
import unittest

from experiments.lab.eval import TaskRuns, by_family, pair_up, paired_diff


def task(task_id, verdicts, family="f", split="sealed"):
    return TaskRuns(task_id, family, split, verdicts)


class PairingInputTests(unittest.TestCase):
    def test_generators_preserve_a_order_and_pair_identity(self):
        a = [task("second", [True, False]), task("first", [True])]
        b = [task("first", [False]), task("second", [False, False])]
        pairs = pair_up(iter(a), iter(b))
        self.assertEqual([x.task_id for x, _ in pairs], ["second", "first"])
        self.assertIs(pairs[0][0], a[0])
        self.assertIs(pairs[0][1], b[1])
        result = paired_diff(a, b, n_boot=64)
        self.assertEqual(result["point"], 0.75)
        self.assertEqual(result["n_runs_min"], 1)
        self.assertEqual(by_family(a, b)["f"]["point"], 0.75)

    def test_reports_missing_tasks_on_both_sides(self):
        output = io.StringIO()
        a = [task("common", [True]), task("only-a", [False])]
        b = [task("only-b", [True]), task("common", [False])]
        with contextlib.redirect_stdout(output):
            pairs = pair_up(a, b)
        self.assertEqual([x.task_id for x, _ in pairs], ["common"])
        self.assertIn("A 臂中缺失", output.getvalue())
        self.assertIn("B 臂中缺失", output.getvalue())
        self.assertIn("only-a", output.getvalue())
        self.assertIn("only-b", output.getvalue())

    def test_rejects_duplicate_ids_in_each_arm(self):
        duplicate = [task("same", [True]), task("same", [False])]
        single = [task("same", [True])]
        for a, b in [(duplicate, single), (single, duplicate)]:
            with self.subTest(duplicated_arm="A" if a is duplicate else "B"):
                with self.assertRaisesRegex(ValueError, "重复 task_id"):
                    paired_diff(a, b, n_boot=8)

    def test_empty_record_is_not_a_zero_pass_rate(self):
        empty = task("same", [])
        with self.assertRaisesRegex(ValueError, "没有判定记录"):
            _ = empty.pass_rate
        full = task("same", [True])
        for a, b in [([empty], [full]), ([full], [empty])]:
            with self.subTest(a_empty=a[0] is empty):
                with self.assertRaisesRegex(ValueError, "没有判定记录"):
                    pair_up(a, b)

    def test_rejects_nonbinary_verdicts(self):
        for values in [[None], [2], [False, 0.5]]:
            with self.subTest(verdicts=values):
                with self.assertRaisesRegex(ValueError, "二元值"):
                    pair_up([task("same", values)], [task("same", [True])])

    def test_numeric_binary_verdicts_remain_supported(self):
        result = paired_diff([task("t", [1, 0])], [task("t", [0, 0])], n_boot=8)
        self.assertEqual(result["point"], 0.5)

    def test_rejects_mismatched_family_or_split(self):
        for b in [task("same", [False], family="other"), task("same", [False], split="train")]:
            with self.subTest(family=b.family, split=b.split):
                with self.assertRaisesRegex(ValueError, "任务族或划分"):
                    pair_up([task("same", [True])], [b])

    def test_no_common_tasks_cannot_produce_an_effect(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "没有可配对的题"):
                paired_diff([task("a", [True])], [task("b", [False])], n_boot=8)

    def test_rejects_nonpositive_bootstrap_count(self):
        for count in [0, -1]:
            with self.subTest(n_boot=count):
                with self.assertRaisesRegex(ValueError, "n_boot"):
                    paired_diff([task("t", [True])], [task("t", [False])], n_boot=count)


if __name__ == "__main__":
    unittest.main()
