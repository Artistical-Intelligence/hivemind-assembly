"""Pure HA shift-window planning tests. No ChatGPT runtime or GitHub needed."""

import unittest

from hivemind_assembly.automation.shift_window import best_shift_manager_phase


class ShiftWindowTests(unittest.TestCase):
    def test_picks_earliest_ready_phase_for_most_manager_work_time(self):
        # Relevant results are available by :56. With a two-minute
        # readiness guard, :58 leaves more room before next-hour :20
        # than the older fixed :08 schedule (offset 68).
        plan = best_shift_manager_phase(
            [54, 55, 56], 80,
            readiness_quantile=1,
            readiness_buffer=2,
            possible_late_start=1,
            update_buffer=1,
        )
        self.assertEqual(plan.minute_of_hour, 58)
        self.assertEqual(plan.planned_offset_minutes, 58)
        self.assertEqual(plan.evidence_ready_offset_minutes, 58)
        self.assertEqual(plan.usable_runway_minutes, 20)
        self.assertEqual(plan.status, "provisional_recommendation")
        self.assertGreater(plan.usable_runway_minutes, 80 - 68 - 1 - 1)

    def test_correctly_wraps_into_next_hour(self):
        plan = best_shift_manager_phase(
            [58, 59], 80,
            readiness_quantile=1,
            readiness_buffer=2,
        )
        self.assertEqual(plan.minute_of_hour, 1)
        self.assertEqual(plan.planned_offset_minutes, 61)
        self.assertEqual(plan.usable_runway_minutes, 18)

    def test_accounts_for_early_start_variance(self):
        plan = best_shift_manager_phase(
            [55, 56], 80,
            readiness_quantile=1,
            readiness_buffer=1,
            possible_early_start=2,
        )
        self.assertEqual(plan.evidence_ready_offset_minutes, 59)
        self.assertEqual(plan.minute_of_hour, 59)
        self.assertEqual(plan.usable_runway_minutes, 20)

    def test_no_feasible_window_does_not_pause_workers(self):
        plan = best_shift_manager_phase(
            [79], 80,
            readiness_quantile=1,
            readiness_buffer=2,
        )
        self.assertIsNone(plan.minute_of_hour)
        self.assertIsNone(plan.planned_offset_minutes)
        self.assertEqual(plan.status, "no_pre_wave_window")
        self.assertEqual(plan.usable_runway_minutes, 0)
        self.assertIn("independent workers continue", plan.explanation)

    def test_quantile_excludes_outlier_without_hiding_it(self):
        samples = [54, 55, 56, 150]
        plan = best_shift_manager_phase(
            samples, 80,
            readiness_quantile=0.75,
            readiness_buffer=1,
        )
        self.assertEqual(plan.minute_of_hour, 57)
        strict = best_shift_manager_phase(
            samples, 80,
            readiness_quantile=1,
            readiness_buffer=1,
        )
        self.assertEqual(strict.status, "no_pre_wave_window")

    def test_preserves_inputs_and_is_deterministic(self):
        samples = [55, 57, 56]
        before = samples.copy()
        first = best_shift_manager_phase(samples, 80, readiness_quantile=1)
        second = best_shift_manager_phase(samples, 80, readiness_quantile=1)
        self.assertEqual(first, second)
        self.assertEqual(samples, before)

    def test_rejects_unusable_or_speculative_metrics(self):
        with self.assertRaises(ValueError):
            best_shift_manager_phase([], 80)
        with self.assertRaises(ValueError):
            best_shift_manager_phase([float("nan")], 80)
        with self.assertRaises(ValueError):
            best_shift_manager_phase([12], 80, readiness_quantile=0)
        with self.assertRaises(ValueError):
            best_shift_manager_phase([12], 80, readiness_quantile=2)
        with self.assertRaises(ValueError):
            best_shift_manager_phase([12], 80, update_buffer=-1)
        with self.assertRaises(ValueError):
            best_shift_manager_phase([False], 80)


if __name__ == "__main__":
    unittest.main()
