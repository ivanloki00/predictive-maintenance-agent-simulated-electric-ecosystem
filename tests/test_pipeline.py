import unittest
import uuid
from datetime import datetime, timedelta, timezone

from predictive_maintenance.pipeline import (
    WindowProcessingConfig,
    process_dataset_windows,
)
from predictive_maintenance.simulator import (
    DegradationMode,
    SyntheticRunConfig,
    generate_dataset,
)
from predictive_maintenance.windowing import (
    NBRegimeConfig,
    Regime,
    SolarRegimeConfig,
    WindowStatus,
    WindowingConfig,
)


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def run_config(index, profile, *, nb_idle_sampling_period_ms=None):
    return SyntheticRunConfig(
        run_id=str(uuid.UUID(int=index, version=4)),
        asset_id=f"asset-{index}",
        profile=profile,
        seed=index,
        started_at=START + timedelta(days=index),
        duration_s=60,
        physical_step_ms=250,
        sampling_period_ms=1000,
        prediction_horizon_s=10,
        degradation_mode=DegradationMode.NONE,
        degradation_onset_fraction=0.5,
        ambient_temperature_c=25,
        sensor_noise_stddev=0,
        nominal_power_kw=120,
        thermal_time_constant_s=2,
        temperature_rise_at_full_load_c=20,
        insulation_baseline_megaohm=50,
        esr_baseline_mohm=2,
        thermal_failure_threshold_c=130,
        esr_failure_ratio=3,
        insulation_failure_megaohm=1,
        nb_idle_sampling_period_ms=nb_idle_sampling_period_ms,
    )


def processing_config():
    return WindowProcessingConfig(
        solar=SolarRegimeConfig(irradiance_on_w_m2=200, irradiance_off_w_m2=100, debounce_s=0),
        nb=NBRegimeConfig(ramp_threshold_kw_per_s=5, debounce_s=0),
        windows=WindowingConfig(
            sampling_period_ms=1000,
            max_gap_s=2,
            max_history_s=5,
            stride_s=5,
            max_samples=6,
            durations_s={
                Regime.SOLAR_ACTIVE: 2,
                Regime.SOLAR_LOW: 2,
                Regime.IDLE: 2,
                Regime.CHARGING_STEADY: 2,
                Regime.CHARGING_RAMP: 2,
            },
        ),
    )


class DatasetWindowPipelineTests(unittest.TestCase):
    def test_processes_both_profiles_and_forces_windows_on_regime_changes(self):
        dataset = generate_dataset(
            [
                run_config(301, "solar_utility"),
                run_config(302, "ev_nb"),
                run_config(303, "solar_utility"),
                run_config(304, "ev_nb"),
            ],
            train_fraction=0.5,
            validation_fraction=0.25,
        )
        frames = process_dataset_windows(dataset, processing_config())
        self.assertTrue(frames)
        self.assertEqual(
            {frame.run_id for frame in frames},
            {run["run_id"] for run in dataset.manifest["runs"]},
        )
        self.assertIn(Regime.SOLAR_LOW, {frame.regime for frame in frames})
        self.assertIn(Regime.CHARGING_RAMP, {frame.regime for frame in frames})
        self.assertTrue(
            any(frame.status == WindowStatus.INSUFFICIENT_HISTORY for frame in frames)
        )
        for frame in frames:
            self.assertTrue(all(index >= 0 for index in frame.sample_indices))

    def test_windowing_configuration_can_be_persisted_with_units_and_provenance(self):
        manifest_config = processing_config().as_manifest()
        self.assertEqual(manifest_config["sampling_period_ms"], 1000)
        self.assertEqual(manifest_config["stride_s"], 5)
        self.assertEqual(
            manifest_config["parameter_status"], "synthetic_unvalidated"
        )
        self.assertEqual(
            manifest_config["durations_s"]["charging_ramp"], 2
        )
        self.assertEqual(
            manifest_config["minimum_samples"]["charging_ramp"], 3
        )
        self.assertEqual(
            manifest_config["parameter_provenance"]["nb"][
                "ramp_threshold_kw_per_s"
            ]["unit"],
            "kW/s",
        )
        self.assertEqual(
            manifest_config["parameter_provenance"]["solar"]["irradiance_on_w_m2"][
                "confidence"
            ],
            "low",
        )

    def test_inference_windowing_ignores_top_level_ground_truth(self):
        dataset = generate_dataset(
            [run_config(index, "solar_utility") for index in range(401, 404)],
            train_fraction=1 / 3,
            validation_fraction=1 / 3,
        )
        telemetry = list(dataset.telemetry)
        telemetry[0] = {**telemetry[0], "ground_truth": {"junction_temp_c": 0}}
        from predictive_maintenance.simulator import SyntheticDataset

        invalid_dataset = SyntheticDataset(
            telemetry=tuple(telemetry),
            labels=dataset.labels,
            manifest=dataset.manifest,
        )
        self.assertEqual(
            process_dataset_windows(invalid_dataset, processing_config()),
            process_dataset_windows(dataset, processing_config()),
        )

    def test_pipeline_preserves_history_across_expected_nb_idle_interval(self):
        runs = [
            run_config(index, "ev_nb", nb_idle_sampling_period_ms=5000)
            for index in range(501, 504)
        ]
        dataset = generate_dataset(
            runs, train_fraction=1 / 3, validation_fraction=1 / 3
        )
        target_run_id = runs[0].run_id
        idle_rows = [
            row
            for row in dataset.telemetry
            if row["run_id"] == target_run_id
            and row["next_expected_interval_ms"] == 5000
        ]
        self.assertGreaterEqual(len(idle_rows), 2)
        frames = process_dataset_windows(dataset, processing_config())
        frame_at_next_idle_sample = next(
            frame
            for frame in frames
            if frame.run_id == target_run_id
            and frame.timestamp == idle_rows[1]["timestamp"]
        )
        self.assertGreaterEqual(len(frame_at_next_idle_sample.sample_indices), 2)


if __name__ == "__main__":
    unittest.main()
