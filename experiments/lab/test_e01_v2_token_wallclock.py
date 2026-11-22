"""Counter-example tests for the offline token / wall-clock hard ceilings.

These tests prove the hard ceilings actually stop an over-limit call and an
over-time run (R11.5 / E01-v2-draft §13-16 line 39/113/137). They are offline:
no backend, no paid execution, no OS isolation. The assembly tests confirm the
guard is consulted on the synthetic U extraction and that the permissive default
preserves existing behavior (no regression).
"""
import unittest
import tempfile
from .e01_v2_token_wallclock import (HardCeiling, HardCeilingGuard,
    TokenCeilingExceeded, WallClockExceeded)
from .e01_v2_assembly import run_e01_v2_assembly


class TokenCeilingChecks(unittest.TestCase):
    def test_at_limit_is_allowed(self):
        g = HardCeilingGuard(HardCeiling(10, 100.0))
        g.check_call_tokens(10)  # boundary
        g.check_call_tokens(0)

    def test_over_limit_raises(self):
        g = HardCeilingGuard(HardCeiling(10, 100.0))
        with self.assertRaises(TokenCeilingExceeded):
            g.check_call_tokens(11)

    def test_negative_tokens_rejected(self):
        with self.assertRaises(ValueError):
            HardCeiling(-1, 100.0)

    def test_negative_wallclock_ceiling_rejected(self):
        with self.assertRaises(ValueError):
            HardCeiling(10, -1.0)

    def test_nonfinite_wallclock_ceiling_rejected(self):
        for seconds in [float('nan'), float('inf'), float('-inf')]:
            with self.subTest(seconds=seconds):
                with self.assertRaises(ValueError):
                    HardCeiling(10, seconds)

    def test_large_integer_wallclock_ceiling_remains_supported(self):
        guard = HardCeilingGuard(HardCeiling(10, 10**400))
        self.assertEqual(guard.accumulate_wall_clock(1.0), 1.0)


class WallClockChecks(unittest.TestCase):
    def test_under_limit_accumulates(self):
        g = HardCeilingGuard(HardCeiling(10**9, 5.0))
        self.assertEqual(g.accumulate_wall_clock(2.0), 2.0)
        self.assertEqual(g.accumulate_wall_clock(2.9), 4.9)  # still < 5.0

    def test_over_limit_raises(self):
        g = HardCeilingGuard(HardCeiling(10**9, 5.0))
        g.accumulate_wall_clock(3.0)
        with self.assertRaises(WallClockExceeded):
            g.accumulate_wall_clock(2.5)  # 5.5 > 5.0

    def test_zero_limit_rejects_first_unit(self):
        g = HardCeilingGuard(HardCeiling(10**9, 0.0))
        with self.assertRaises(WallClockExceeded):
            g.accumulate_wall_clock(0.1)

    def test_negative_elapsed_rejected(self):
        g = HardCeilingGuard(HardCeiling(10**9, 100.0))
        with self.assertRaises(ValueError):
            g.accumulate_wall_clock(-1.0)

    def test_nonfinite_elapsed_preserves_counter_and_stop(self):
        for seconds in [float('nan'), float('inf'), float('-inf')]:
            with self.subTest(seconds=seconds):
                guard = HardCeilingGuard(HardCeiling(10, 1.0))
                guard.accumulate_wall_clock(0.5)
                with self.assertRaises(ValueError):
                    guard.accumulate_wall_clock(seconds)
                self.assertEqual(guard.elapsed_wall_clock, 0.5)
                self.assertEqual(guard.accumulate_wall_clock(0.5), 1.0)
                with self.assertRaises(WallClockExceeded):
                    guard.accumulate_wall_clock(0.25)


class AssemblyHardLimitChecks(unittest.TestCase):
    def test_permissive_default_no_regression(self):
        out = run_e01_v2_assembly(tempfile.mkdtemp(), 'twc-permissive')
        self.assertEqual(out['api_calls'], 0)
        self.assertTrue(out['merged_lesson_in_bound_store'])
        self.assertIn('token_wallclock_scope', out)

    def test_token_ceiling_rejects_in_assembly(self):
        # The synthetic settle uses completion_tokens=1; a per-call ceiling of 0
        # makes the first U extraction raise before settlement.
        with self.assertRaises(TokenCeilingExceeded):
            run_e01_v2_assembly(tempfile.mkdtemp(), 'twc-tok',
                                ceiling=HardCeiling(0, 10**9))

    def test_wall_clock_stop_in_assembly(self):
        # A whole-run stop condition of 0s rejects as soon as the first U unit
        # charges its simulated elapsed wall-clock.
        with self.assertRaises(WallClockExceeded):
            run_e01_v2_assembly(tempfile.mkdtemp(), 'twc-clock',
                                ceiling=HardCeiling(10**9, 0.0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
