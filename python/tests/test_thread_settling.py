from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation"))

from thread_settling import SettlingConfig, load_drawdown, simulate_settling


class ThreadSettlingTests(unittest.TestCase):
    def test_simulation_builds_fixed_discretized_cylinder_threads(self):
        drawdown = [
            [1, 0, 1],
            [0, 1, 0],
        ]
        config = SettlingConfig(cylinders_per_cell=4, iterations=30)
        result = simulate_settling(drawdown, config)

        self.assertEqual(result.drawdown, drawdown)
        self.assertEqual(len([thread for thread in result.threads if thread.kind == "warp"]), 3)
        self.assertEqual(len([thread for thread in result.threads if thread.kind == "weft"]), 2)
        self.assertEqual(result.cylinder_count, sum(thread.cylinder_count for thread in result.threads))
        self.assertEqual(result.spring_count, result.cylinder_count)
        self.assertLessEqual(result.max_penetration, 1e-7)

        for thread in result.threads:
            self.assertTrue(thread.fixed[0])
            self.assertTrue(thread.fixed[-1])
            self.assertEqual(thread.nodes[0][2], 0.0)
            self.assertEqual(thread.nodes[-1][2], 0.0)
            self.assertGreater(thread.cylinder_count, 0)

    def test_discretization_parameter_changes_cylinder_count(self):
        drawdown = [[1, 0], [0, 1]]
        coarse = simulate_settling(drawdown, SettlingConfig(cylinders_per_cell=1, iterations=10))
        fine = simulate_settling(drawdown, SettlingConfig(cylinders_per_cell=4, iterations=10))

        self.assertGreater(fine.cylinder_count, coarse.cylinder_count)
        self.assertGreater(fine.node_count, coarse.node_count)

    def test_thread_diameter_changes_rendered_width_without_changing_spacing(self):
        drawdown = [[1, 0], [0, 1]]
        narrow = simulate_settling(drawdown, SettlingConfig(thread_diameter=0.5, cylinders_per_cell=2, iterations=10))
        wide = simulate_settling(drawdown, SettlingConfig(thread_diameter=1.0, cylinders_per_cell=2, iterations=10))

        self.assertEqual(narrow.thread_spacing, wide.thread_spacing)
        self.assertLess(narrow.thread_diameter, wide.thread_diameter)
        self.assertIn('"threadDiameter":0.5', narrow.to_html(iframe=False))
        self.assertIn('"threadDiameter":1.0', wide.to_html(iframe=False))
        self.assertIn('"threadSpacing":1.25', narrow.to_html(iframe=False))
        self.assertIn('"threadSpacing":1.25', wide.to_html(iframe=False))

    def test_interlacing_starts_from_drawdown_order(self):
        drawdown = [
            [1, 0],
            [0, 1],
        ]
        result = simulate_settling(drawdown, SettlingConfig(cylinders_per_cell=3, iterations=20))

        for row in range(len(drawdown)):
            for col in range(len(drawdown[0])):
                self.assertGreater(result.crossing_clearance(row, col), 0.0)

    def test_load_drawdown_accepts_json_literal(self):
        self.assertEqual(load_drawdown("[[1, 0], [0, 1]]"), [[1, 0], [0, 1]])

    def test_rejects_invalid_inputs(self):
        with self.assertRaises(ValueError):
            simulate_settling([[1, 2]])
        with self.assertRaises(ValueError):
            simulate_settling([[1]], SettlingConfig(cylinders_per_cell=0))
        with self.assertRaises(ValueError):
            simulate_settling([[1]], SettlingConfig(thread_diameter=1.0, thread_spacing=0.5))

    def test_result_serializes_cylinders(self):
        result = simulate_settling([[1, 0]], SettlingConfig(cylinders_per_cell=2, iterations=10))
        data = result.to_dict()
        cylinders = result.cylinders()

        self.assertEqual(data["cylinder_count"], len(cylinders))
        self.assertIn("spring_constant", data["config"])
        self.assertIn("start", cylinders[0])
        self.assertIn("end", cylinders[0])
        self.assertEqual(cylinders[0]["radius"], result.thread_radius)

    def test_settled_fabric_draws_interactive_3d_html(self):
        result = simulate_settling([[1, 1], [0, 0]], SettlingConfig(cylinders_per_cell=2, iterations=10))
        drawing = result.draw_3d(canvas_width=320, canvas_height=240)
        html = drawing._repr_html_()

        self.assertIn("<iframe", html)
        self.assertIn("srcdoc=", html)
        self.assertIn("fabric-viewer", html)
        self.assertIn("drawSmoothThread", html)
        self.assertEqual(str(drawing), html)

        with TemporaryDirectory() as temp_dir:
            output_path = result.save_html(Path(temp_dir) / "settled.html", canvas_width=320, canvas_height=240)
            saved = output_path.read_text(encoding="utf-8")
            self.assertIn("<canvas", saved)
            self.assertIn("pointermove", saved)
            self.assertIn("catmullRom", saved)
            self.assertIn('"threadDiameter":1.0', saved)
            self.assertIn('"cylinderCount":', saved)


if __name__ == "__main__":
    unittest.main()
