import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predictive_maintenance.simulator import (
    DegradationMode,
    SyntheticMilestoneConfig,
    SyntheticRunConfig,
    generate_dataset,
    simulate_run,
    write_dataset,
)


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def run_config(
    index,
    *,
    profile="solar_utility",
    mode=DegradationMode.IGBT_THERMAL_FATIGUE,
    duration_s=10,
    nb_idle_sampling_period_ms=None,
    milestones=None,
):
    return SyntheticRunConfig(
        run_id=str(uuid.UUID(int=index, version=4)),
        asset_id=f"asset-{index}",
        profile=profile,
        seed=index,
        started_at=START + timedelta(days=index),
        duration_s=duration_s,
        physical_step_ms=250,
        sampling_period_ms=1000,
        prediction_horizon_s=5,
        degradation_mode=mode,
        degradation_onset_fraction=0.2,
        ambient_temperature_c=25,
        sensor_noise_stddev=0.1,
        nominal_power_kw=120,
        thermal_time_constant_s=2,
        temperature_rise_at_full_load_c=20,
        insulation_baseline_megaohm=50,
        esr_baseline_mohm=2,
        thermal_failure_threshold_c=130,
        esr_failure_ratio=3,
        insulation_failure_megaohm=1,
        nb_idle_sampling_period_ms=nb_idle_sampling_period_ms,
        milestones=milestones or SyntheticMilestoneConfig(),
    )


class SyntheticSimulatorTests(unittest.TestCase):
    def test_reproducible_telemetry_and_separate_labels(self):
        config = run_config(1)
        first = simulate_run(config)
        second = simulate_run(config)
        self.assertEqual(first.telemetry, second.telemetry)
        self.assertEqual(first.labels, second.labels)
        self.assertEqual(len(first.telemetry), 11)
        self.assertEqual(first.telemetry[0]["schema_version"], "1.0.0")
        self.assertNotIn("ground_truth", first.telemetry[0])
        self.assertIn("ground_truth", first.labels[0])
        self.assertEqual(
            first.telemetry[0]["timestamp"], first.labels[0]["timestamp"]
        )

    def test_generates_profile_specific_fields_and_missing_quality_mask(self):
        solar = simulate_run(
            run_config(2, profile="solar_utility", duration_s=60)
        )
        nb = simulate_run(run_config(3, profile="ev_nb", duration_s=60))
        self.assertIsNone(solar.telemetry[0]["observables"]["ev_power_kw"])
        self.assertIsNotNone(solar.telemetry[0]["observables"]["irradiance_w_m2"])
        self.assertIsNone(nb.telemetry[0]["observables"]["irradiance_w_m2"])
        self.assertIsNotNone(nb.telemetry[0]["observables"]["ev_session_active"])
        self.assertEqual(
            solar.telemetry[0]["quality"]["missing_fields"], []
        )
        self.assertIn(
            "observables.irradiance_w_m2",
            solar.telemetry[53]["quality"]["missing_fields"],
        )

    def test_nb_idle_cadence_is_emitted_and_recorded_per_sample(self):
        run = simulate_run(
            run_config(
                33,
                profile="ev_nb",
                duration_s=120,
                nb_idle_sampling_period_ms=5000,
            )
        )
        timestamps = [
            datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            for row in run.telemetry
        ]
        intervals = [
            (later - earlier).total_seconds()
            for earlier, later in zip(timestamps, timestamps[1:])
        ]
        self.assertIn(5, intervals)
        idle_row = next(
            row for row in run.telemetry
            if row["observables"]["ev_session_active"] is False
        )
        self.assertEqual(idle_row["next_expected_interval_ms"], 5000)
        dataset = generate_dataset(
            [
                run.config,
                run_config(
                    34,
                    profile="ev_nb",
                    duration_s=120,
                    nb_idle_sampling_period_ms=5000,
                ),
                run_config(35, profile="ev_nb", duration_s=120),
            ],
            train_fraction=1 / 3,
            validation_fraction=1 / 3,
        )
        run_manifest = dataset.manifest["runs"][0]
        self.assertEqual(run_manifest["telemetry_schedule"]["mode"], "nb_session_idle")
        self.assertEqual(
            run_manifest["telemetry_schedule"]["idle_interval_ms"], 5000
        )

    def test_labels_capture_degradation_onset_and_censor_healthy_run(self):
        degraded = simulate_run(run_config(4))
        healthy = simulate_run(run_config(5, mode=DegradationMode.NONE))
        self.assertIsNotNone(degraded.event_onset_utc)
        self.assertIsNotNone(degraded.failure_time_utc)
        self.assertIsNone(healthy.event_onset_utc)
        self.assertIsNone(healthy.failure_time_utc)
        healthy_truth = healthy.labels[-1]["ground_truth"]
        self.assertIsNone(healthy_truth["predictive_warning_target_utc"])
        self.assertIsNone(healthy_truth["synthetic_protection_event_utc"])
        self.assertIsNone(healthy_truth["end_of_life_event_utc"])
        self.assertFalse(healthy_truth["synthetic_protection_active"])
        self.assertFalse(healthy_truth["end_of_life_reached"])
        self.assertEqual(
            healthy.labels[-1]["ground_truth"]["failure_within_horizon"], False
        )
        self.assertEqual(
            degraded.labels[-1]["ground_truth"]["degradation_state"], "critical"
        )
        self.assertTrue(
            degraded.labels[5]["ground_truth"]["failure_within_horizon"]
        )
        self.assertIsNotNone(
            degraded.labels[0]["ground_truth"]["failure_time_utc"]
        )

    def test_warning_protection_and_eol_have_distinct_configured_labels(self):
        run = simulate_run(
            run_config(
                6,
                milestones=SyntheticMilestoneConfig(
                    predictive_warning_damage_fraction=0.25,
                    synthetic_protection_damage_fraction=0.5,
                    end_of_life_damage_fraction=0.75,
                ),
            )
        )
        first_truth = run.labels[0]["ground_truth"]
        self.assertEqual(
            first_truth["predictive_warning_target_utc"],
            "2026-01-07T00:00:04.000Z",
        )
        self.assertEqual(
            first_truth["synthetic_protection_event_utc"],
            "2026-01-07T00:00:06.000Z",
        )
        self.assertEqual(
            first_truth["end_of_life_event_utc"],
            "2026-01-07T00:00:08.000Z",
        )
        self.assertFalse(
            run.labels[3]["ground_truth"]["predictive_warning_target_active"]
        )
        self.assertTrue(
            run.labels[4]["ground_truth"]["predictive_warning_target_active"]
        )
        self.assertFalse(
            run.labels[5]["ground_truth"]["synthetic_protection_active"]
        )
        self.assertTrue(
            run.labels[6]["ground_truth"]["synthetic_protection_active"]
        )
        self.assertFalse(run.labels[7]["ground_truth"]["end_of_life_reached"])
        self.assertTrue(run.labels[8]["ground_truth"]["end_of_life_reached"])

    def test_milestones_require_strictly_increasing_damage_fractions(self):
        with self.assertRaises(ValueError):
            SyntheticMilestoneConfig(
                predictive_warning_damage_fraction=0.8,
                synthetic_protection_damage_fraction=0.7,
                end_of_life_damage_fraction=1.0,
            )

    def test_partitions_are_assigned_to_runs_and_saved_in_manifest(self):
        configs = [run_config(index) for index in range(10, 14)]
        dataset = generate_dataset(
            configs, train_fraction=0.5, validation_fraction=0.25
        )
        groups = {item["run_id"]: item["eval_group"] for item in dataset.manifest["runs"]}
        self.assertEqual(len(groups), 4)
        self.assertEqual(sum(group == "train" for group in groups.values()), 2)
        self.assertEqual(
            sum(group == "validation" for group in groups.values()), 1
        )
        self.assertEqual(sum(group == "test" for group in groups.values()), 1)
        self.assertTrue(
            all(item["config"]["parameter_status"] == "synthetic_unvalidated"
                for item in dataset.manifest["runs"])
        )
        milestone = dataset.manifest["runs"][0]["config"]["event_milestones"]
        self.assertEqual(
            milestone["synthetic_protection"]["status"], "synthetic_unvalidated"
        )
        self.assertEqual(
            milestone["end_of_life"]["source"], "synthetic scenario assumption"
        )
        parameter = dataset.manifest["runs"][0]["config"]["parameter_provenance"][
            "thermal_failure_threshold_c"
        ]
        self.assertEqual(parameter["unit"], "degC")
        self.assertEqual(parameter["status"], "synthetic_unvalidated")

    def test_writes_parseable_separate_artifacts(self):
        dataset = generate_dataset(
            [run_config(index) for index in range(20, 23)],
            train_fraction=1 / 3,
            validation_fraction=1 / 3,
        )
        with tempfile.TemporaryDirectory() as output:
            write_dataset(dataset, output)
            telemetry_path = Path(output) / "telemetry.jsonl"
            labels_path = Path(output) / "labels.jsonl"
            manifest_path = Path(output) / "manifest.json"
            telemetry_row = json.loads(telemetry_path.read_text(encoding="utf-8").splitlines()[0])
            labels_row = json.loads(labels_path.read_text(encoding="utf-8").splitlines()[0])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn("ground_truth", telemetry_row)
            self.assertIn("ground_truth", labels_row)
            self.assertEqual(len(manifest["runs"]), 3)

    def test_rejects_non_v4_id_and_invalid_cadence(self):
        with self.assertRaises(ValueError):
            SyntheticRunConfig(**{
                **run_config(30).__dict__,
                "run_id": "00000000-0000-0000-0000-000000000001",
            })
        with self.assertRaises(ValueError):
            SyntheticRunConfig(**{
                **run_config(31).__dict__,
                "sampling_period_ms": 2100,
            })
        with self.assertRaises(ValueError):
            SyntheticRunConfig(**{
                **run_config(31).__dict__,
                "duration_s": 9,
                "sampling_period_ms": 2000,
            })
        with self.assertRaises(ValueError):
            SyntheticRunConfig(**{
                **run_config(32).__dict__,
                "physical_step_ms": 300,
            })


if __name__ == "__main__":
    unittest.main()
