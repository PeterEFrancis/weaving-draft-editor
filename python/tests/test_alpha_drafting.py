from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha_drafting import (
    AlgorithmConfig,
    benchmark_random_targets,
    phi_beta,
    random_target,
    run_alpha1,
    run_alpha2,
    run_alpha3,
    run_beta1,
    run_beta2,
    run_beta3,
)


class AlphaDraftingTests(unittest.TestCase):
    def test_random_target_shape_and_values(self):
        target = random_target(width=5, picks=3, probability=0.5, seed=7)
        self.assertEqual(len(target), 3)
        self.assertEqual(len(target[0]), 5)
        self.assertTrue(all(value in (0, 1) for row in target for value in row))

    def test_alpha_algorithms_return_valid_drawdowns(self):
        target = random_target(width=8, picks=6, probability=0.5, seed=11)
        config = AlgorithmConfig(
            shafts=4,
            treadles=6,
            max_pressed=2,
            iteration_limit=4,
            random_restarts=1,
            residual_restarts=1,
            beam_width=2,
            seed=13,
        )
        for runner in (run_alpha1, run_alpha2, run_alpha3):
            with self.subTest(runner=runner.__name__):
                candidate = runner(target, config)
                self.assertEqual(len(candidate.drawdown), len(target))
                self.assertEqual(len(candidate.drawdown[0]), len(target[0]))
                self.assertGreaterEqual(candidate.hamming_error, 0)
                self.assertLessEqual(candidate.hamming_error, len(target) * len(target[0]))
                self.assertLessEqual(len(candidate.threading), config.shafts)
                self.assertLessEqual(len(candidate.tieup), config.treadles)
                self.assertLessEqual(candidate.max_pressed_used, config.max_pressed)

    def test_phi_beta_can_use_open_boundary_with_equal_black_count(self):
        source = [[1, 0, 0, 0, 0, 0, 0, 0, 0, 0]]
        target = [[0, 0, 0, 0, 0, 0, 0, 0, 0, 1]]
        self.assertEqual(phi_beta(source, target), 2)

    def test_phi_beta_prefers_adjacent_movement_when_cheaper(self):
        source = [[0, 0, 0, 1, 0, 0]]
        target = [[0, 0, 0, 0, 1, 0]]
        self.assertEqual(phi_beta(source, target), 1)

    def test_beta_algorithms_return_movement_scores(self):
        target = random_target(width=6, picks=5, probability=0.5, seed=41)
        config = AlgorithmConfig(
            shafts=3,
            treadles=4,
            max_pressed=2,
            iteration_limit=3,
            random_restarts=0,
            residual_restarts=1,
            beam_width=1,
            seed=43,
        )
        for runner in (run_beta1, run_beta2, run_beta3):
            with self.subTest(runner=runner.__name__):
                candidate = runner(target, config)
                self.assertEqual(len(candidate.drawdown), len(target))
                self.assertIsNotNone(candidate.movement_cost)
                self.assertEqual(candidate.movement_cost, phi_beta(candidate.drawdown, target))
                self.assertLessEqual(candidate.max_pressed_used, config.max_pressed)

    def test_benchmark_smoke(self):
        config = AlgorithmConfig(
            shafts=3,
            treadles=4,
            max_pressed=2,
            iteration_limit=3,
            random_restarts=0,
            residual_restarts=0,
            beam_width=1,
            seed=17,
        )
        rows = benchmark_random_targets(
            algorithms=["alpha1", "alpha2", "beta1"],
            sizes=[(5, 4)],
            config=config,
            trials=2,
            probability=0.5,
            seed=19,
        )
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["trials"] == 2 for row in rows))
        beta_row = next(row for row in rows if row["algorithm"] == "beta1")
        self.assertIsNotNone(beta_row["mean_movement"])

    def test_benchmark_progress_callback_reports_each_run(self):
        config = AlgorithmConfig(
            shafts=3,
            treadles=4,
            max_pressed=2,
            iteration_limit=2,
            random_restarts=0,
            residual_restarts=0,
            beam_width=1,
            seed=23,
        )
        events = []

        benchmark_random_targets(
            algorithms=["alpha1", "alpha2"],
            sizes=[(4, 3), (5, 4)],
            config=config,
            trials=2,
            probability=0.5,
            seed=29,
            progress_callback=lambda completed, total, label: events.append((completed, total, label)),
        )

        self.assertEqual(len(events), 8)
        self.assertEqual(events[0][0], 1)
        self.assertEqual(events[-1][0], events[-1][1])
        self.assertTrue(all(total == 8 for _, total, _ in events))
        self.assertTrue(all(label.startswith("alpha") for _, _, label in events))

    def test_parallel_benchmark_matches_serial_error_statistics(self):
        config = AlgorithmConfig(
            shafts=3,
            treadles=4,
            max_pressed=2,
            iteration_limit=2,
            random_restarts=0,
            residual_restarts=0,
            beam_width=1,
            seed=31,
        )
        kwargs = {
            "algorithms": ["alpha1", "alpha2"],
            "sizes": [(4, 3), (5, 4)],
            "config": config,
            "trials": 2,
            "probability": 0.5,
            "seed": 37,
        }

        serial_rows = benchmark_random_targets(**kwargs, jobs=1)
        try:
            parallel_rows = benchmark_random_targets(**kwargs, jobs=2)
        except PermissionError as exc:
            raise unittest.SkipTest(f"process pools are unavailable in this environment: {exc}")

        self.assertEqual(len(serial_rows), len(parallel_rows))
        for serial, parallel in zip(serial_rows, parallel_rows):
            for key in (
                "algorithm",
                "width",
                "picks",
                "trials",
                "mean_error",
                "stdev_error",
                "mean_error_rate",
                "stdev_error_rate",
            ):
                self.assertEqual(serial[key], parallel[key])


if __name__ == "__main__":
    unittest.main()
