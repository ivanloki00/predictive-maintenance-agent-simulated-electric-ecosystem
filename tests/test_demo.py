import json
import tempfile
import unittest
from pathlib import Path

from predictive_maintenance.demo import run_demo


class SyntheticDemoTests(unittest.TestCase):
    def test_demo_outputs_are_reproducible_and_record_test_metrics(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first_report = run_demo(Path(first_dir), seed=42)
            second_report = run_demo(Path(second_dir), seed=42)
            self.assertEqual(first_report, second_report)
            self.assertEqual(first_report["test_run_count"], 2)
            self.assertTrue(first_report["synthetic_unvalidated"])
            for name in (
                "telemetry.jsonl",
                "labels.jsonl",
                "manifest.json",
                "windows.jsonl",
                "evaluation.json",
            ):
                first = (Path(first_dir) / name).read_bytes()
                second = (Path(second_dir) / name).read_bytes()
                self.assertEqual(first, second, name)
            telemetry_row = json.loads(
                (Path(first_dir) / "telemetry.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            labels_row = json.loads(
                (Path(first_dir) / "labels.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            self.assertNotIn("ground_truth", telemetry_row)
            self.assertIn("ground_truth", labels_row)
            manifest = json.loads(
                (Path(first_dir) / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["windowing"]["sampling_period_ms"], 1000)
            self.assertEqual(manifest["runs"][0]["physical_step_ms"], 250)
            self.assertEqual(
                manifest["evaluation"]["thermal_threshold_c"]["status"],
                "synthetic_unvalidated",
            )
            self.assertEqual(
                manifest["baseline"]["parameters"]["thermal_time_constant_s"][
                    "unit"
                ],
                "s",
            )
            self.assertIsNotNone(first_report["forecast_temperature_metrics"])
            self.assertIsNone(first_report["event_cost_config"])
            self.assertIn("solar_low", first_report["temperature_metrics_by_regime"])
            self.assertIn(
                "insulation",
                first_report["temperature_metrics_by_scenario"],
            )


if __name__ == "__main__":
    unittest.main()
