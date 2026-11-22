import unittest
import uuid
from datetime import datetime, timedelta, timezone

from predictive_maintenance.baseline import (
    RCBaselineConfig,
    RCTemperatureBaseline,
    evaluate_rc_baseline,
)
from predictive_maintenance.evaluation import EvaluationConfig
from predictive_maintenance.simulator import (
    DegradationMode,
    SyntheticRunConfig,
    generate_dataset,
)
from predictive_maintenance.windowing import (
    NBRegimeConfig,
    SolarRegimeConfig,
)


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def run_config(index, *, profile="solar_utility", mode=DegradationMode.IGBT_THERMAL_FATIGUE):
    return SyntheticRunConfig(
        run_id=str(uuid.UUID(int=index, version=4)),
        asset_id=f"asset-{index}",
        profile=profile,
        seed=index,
        started_at=START + timedelta(days=index),
        duration_s=10,
        physical_step_ms=250,
        sampling_period_ms=1000,
        prediction_horizon_s=5,
        degradation_mode=mode,
        degradation_onset_fraction=0.2,
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
    )


class RCBaselineTests(unittest.TestCase):
    def setUp(self):
        self.config = RCBaselineConfig(
            nominal_power_kw={"solar_utility": 120, "ev_nb": 120},
            temperature_rise_at_full_load_c=20,
            thermal_time_constant_s=2,
        )

    def test_estimator_uses_only_observables_and_causal_state(self):
        sample = {
            "profile": "solar_utility",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "observables": {
                "heatsink_temp_c": 40,
                "dc_bus_voltage_v": 1000,
                "dc_bus_current_a": 60,
            },
            "ground_truth": {"junction_temp_c": -99999},
        }
        baseline = RCTemperatureBaseline(self.config)
        first = baseline.estimate(sample)
        self.assertAlmostEqual(first, 50)
        sample["timestamp"] = "2026-01-01T00:00:01.000Z"
        sample["observables"]["heatsink_temp_c"] = 40
        sample["observables"]["dc_bus_current_a"] = 0
        second = baseline.estimate(sample)
        self.assertGreater(second, 40)
        self.assertLess(second, first)

    def test_rejects_missing_inputs_and_noncausal_timestamps(self):
        baseline = RCTemperatureBaseline(self.config)
        sample = {
            "profile": "ev_nb",
            "timestamp": "2026-01-01T00:00:00Z",
            "observables": {"heatsink_temp_c": 40, "ev_power_kw": 10},
        }
        baseline.estimate(sample)
        with self.assertRaises(ValueError):
            baseline.estimate(sample)
        with self.assertRaises(ValueError):
            RCTemperatureBaseline(self.config).estimate(
                {"profile": "ev_nb", "timestamp": "2026-01-01T00:00:00",
                 "observables": {"heatsink_temp_c": 40, "ev_power_kw": 10}}
            )

    def test_evaluates_only_test_runs_and_reports_metrics_reproducibly(self):
        dataset = generate_dataset(
            [
                run_config(101, mode=DegradationMode.NONE),
                run_config(102),
                run_config(103),
                run_config(104),
            ],
            train_fraction=0.5,
            validation_fraction=0.25,
        )
        eval_config = EvaluationConfig(
            forecast_horizon_s=5,
            thermal_threshold_c=70,
            alarm_cooldown_s=2,
        )
        first = evaluate_rc_baseline(
            dataset,
            baseline_config=self.config,
            evaluation_config=eval_config,
            solar_regime_config=SolarRegimeConfig(200, 100, 0),
            nb_regime_config=NBRegimeConfig(5, 0),
        )
        second = evaluate_rc_baseline(
            dataset,
            baseline_config=self.config,
            evaluation_config=eval_config,
            solar_regime_config=SolarRegimeConfig(200, 100, 0),
            nb_regime_config=NBRegimeConfig(5, 0),
        )
        self.assertEqual(first, second)
        self.assertEqual(first.test_run_count, 1)
        self.assertEqual(first.temperature_metrics.sample_count, 11)
        self.assertIsNotNone(first.forecast_temperature_metrics)
        self.assertEqual(first.forecast_temperature_metrics.sample_count, 6)
        self.assertGreaterEqual(first.temperature_metrics.mae, 0)
        self.assertEqual(first.event_metrics.test_run_count, 1)
        self.assertEqual(
            sum(
                metrics.sample_count
                for metrics in first.temperature_metrics_by_profile.values()
            ),
            first.temperature_metrics.sample_count,
        )
        self.assertEqual(
            sum(
                metrics.sample_count
                for metrics in first.forecast_temperature_metrics_by_profile.values()
            ),
            first.forecast_temperature_metrics.sample_count,
        )
        self.assertEqual(
            sum(
                metrics.test_run_count
                for metrics in first.event_metrics_by_profile.values()
            ),
            first.event_metrics.test_run_count,
        )
        self.assertEqual(
            sum(
                metrics.sample_count
                for metrics in first.temperature_metrics_by_regime.values()
            ),
            first.temperature_metrics.sample_count,
        )

    def test_reports_test_metrics_by_scenario_and_operating_regime(self):
        modes = (
            DegradationMode.NONE,
            DegradationMode.IGBT_THERMAL_FATIGUE,
            DegradationMode.DC_LINK_CAPACITOR,
            DegradationMode.INSULATION,
            DegradationMode.IGBT_THERMAL_FATIGUE,
            DegradationMode.INSULATION,
        )
        dataset = generate_dataset(
            [
                run_config(
                    301 + index,
                    profile="ev_nb" if index == 5 else "solar_utility",
                    mode=mode,
                )
                for index, mode in enumerate(modes)
            ],
            train_fraction=0.5,
            validation_fraction=1 / 6,
        )
        result = evaluate_rc_baseline(
            dataset,
            baseline_config=self.config,
            evaluation_config=EvaluationConfig(5, 70, 2),
            solar_regime_config=SolarRegimeConfig(200, 100, 0),
            nb_regime_config=NBRegimeConfig(5, 0),
        )
        self.assertEqual(
            set(result.temperature_metrics_by_scenario),
            {DegradationMode.IGBT_THERMAL_FATIGUE.value, DegradationMode.INSULATION.value},
        )
        self.assertIn("solar_low", result.temperature_metrics_by_regime)
        self.assertIn("charging_steady", result.temperature_metrics_by_regime)
        self.assertEqual(
            sum(
                metrics.test_run_count
                for metrics in result.event_metrics_by_scenario.values()
            ),
            result.event_metrics.test_run_count,
        )

    def test_fails_if_test_label_is_missing(self):
        dataset = generate_dataset(
            [run_config(index) for index in range(201, 204)],
            train_fraction=1 / 3,
            validation_fraction=1 / 3,
        )
        from predictive_maintenance.simulator import SyntheticDataset

        incomplete = SyntheticDataset(
            telemetry=dataset.telemetry,
            labels=dataset.labels[:-1],
            manifest=dataset.manifest,
        )
        with self.assertRaises(ValueError):
            evaluate_rc_baseline(
                incomplete,
                baseline_config=self.config,
                evaluation_config=EvaluationConfig(5, 70, 2),
            )

    def test_forecast_metric_is_unavailable_without_exact_target_timestamps(self):
        dataset = generate_dataset(
            [run_config(index) for index in range(501, 504)],
            train_fraction=1 / 3,
            validation_fraction=1 / 3,
        )
        result = evaluate_rc_baseline(
            dataset,
            baseline_config=self.config,
            evaluation_config=EvaluationConfig(0.5, 70, 2),
        )
        self.assertIsNone(result.forecast_temperature_metrics)


if __name__ == "__main__":
    unittest.main()
