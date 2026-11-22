import math
import unittest
from datetime import datetime, timedelta, timezone

from predictive_maintenance.windowing import (
    DatasetPartition,
    NBRegimeClassifier,
    NBRegimeConfig,
    Regime,
    SolarRegimeClassifier,
    SolarRegimeConfig,
    TemporalWindowBuffer,
    WindowSample,
    WindowStatus,
    WindowingConfig,
    window_sample_count,
)


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def windowing_config(
    *,
    max_gap_s=2,
    max_history_s=10,
    stride_s=1,
    max_samples=11,
    durations_s=None,
):
    if durations_s is None:
        durations_s = {
            Regime.SOLAR_ACTIVE: 5,
            Regime.SOLAR_LOW: 5,
            Regime.IDLE: 5,
            Regime.CHARGING_STEADY: 5,
            Regime.CHARGING_RAMP: 5,
        }
    return WindowingConfig(
        sampling_period_ms=1000,
        max_gap_s=max_gap_s,
        max_history_s=max_history_s,
        stride_s=stride_s,
        max_samples=max_samples,
        durations_s=durations_s,
    )


def sample(
    index,
    *,
    run_id="run-1",
    asset_id="asset-1",
    timestamp=None,
    next_expected_interval_s=None,
):
    return WindowSample(
        schema_version="1.0.0",
        run_id=run_id,
        sample_index=index,
        timestamp=timestamp or START + timedelta(seconds=index),
        asset_id=asset_id,
        profile="solar_utility",
        observables={"irradiance_w_m2": 500.0},
        features={},
        next_expected_interval_s=next_expected_interval_s,
    )


class WindowSampleCountTests(unittest.TestCase):
    def test_includes_both_endpoints_and_rounds_up(self):
        self.assertEqual(window_sample_count(30, 1), 31)
        self.assertEqual(window_sample_count(1.1, 1), 3)

    def test_rejects_nonpositive_or_nonfinite_inputs(self):
        for duration, period in ((0, 1), (1, 0), (1, math.inf)):
            with self.subTest(duration=duration, period=period):
                with self.assertRaises(ValueError):
                    window_sample_count(duration, period)


class SolarRegimeClassifierTests(unittest.TestCase):
    def setUp(self):
        self.classifier = SolarRegimeClassifier(
            SolarRegimeConfig(
                irradiance_on_w_m2=200,
                irradiance_off_w_m2=100,
                debounce_s=2,
            )
        )

    def test_hysteresis_and_debounce(self):
        self.assertEqual(self.classifier.update(START, 250), Regime.UNKNOWN)
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=2), 250),
            Regime.SOLAR_ACTIVE,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=3), 150),
            Regime.SOLAR_ACTIVE,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=4), 50),
            Regime.SOLAR_ACTIVE,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=6), 50),
            Regime.SOLAR_LOW,
        )

    def test_missing_or_invalid_signal_returns_unknown_and_resets_pending_change(self):
        self.assertEqual(self.classifier.update(START, None), Regime.UNKNOWN)
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=1), 250),
            Regime.UNKNOWN,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=2), float("nan")),
            Regime.UNKNOWN,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=3), 250),
            Regime.UNKNOWN,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=5), 250),
            Regime.SOLAR_ACTIVE,
        )

    def test_rejects_non_utc_and_nonmonotonic_timestamps(self):
        with self.assertRaises(ValueError):
            self.classifier.update(START.replace(tzinfo=None), 250)
        self.classifier.update(START, 250)
        with self.assertRaises(ValueError):
            self.classifier.update(START, 250)


class NBRegimeClassifierTests(unittest.TestCase):
    def setUp(self):
        self.classifier = NBRegimeClassifier(
            NBRegimeConfig(ramp_threshold_kw_per_s=2, debounce_s=2)
        )

    def test_detects_ramp_immediately_and_debounces_return_to_steady(self):
        self.assertEqual(
            self.classifier.update(START, True, 0), Regime.CHARGING_STEADY
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=1), True, 5),
            Regime.CHARGING_RAMP,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=2), True, 5),
            Regime.CHARGING_RAMP,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=3), True, 5),
            Regime.CHARGING_RAMP,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=4), True, 5),
            Regime.CHARGING_STEADY,
        )

    def test_debounces_session_end_and_missing_inputs_return_unknown(self):
        self.classifier.update(START, True, 10)
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=1), False, 0),
            Regime.CHARGING_STEADY,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=3), False, 0),
            Regime.IDLE,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=4), True, None),
            Regime.UNKNOWN,
        )

    def test_ramp_rate_uses_elapsed_time_between_valid_samples(self):
        self.classifier.update(START, True, 0)
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=2), True, 3),
            Regime.CHARGING_STEADY,
        )
        self.assertEqual(
            self.classifier.update(START + timedelta(seconds=3), True, 6),
            Regime.CHARGING_RAMP,
        )


class TemporalWindowBufferTests(unittest.TestCase):
    def setUp(self):
        self.buffer = TemporalWindowBuffer(windowing_config())

    def test_selects_immediately_available_samples_and_reports_duration(self):
        for index in range(6):
            self.buffer.append(sample(index), DatasetPartition.TRAIN)
        selection = self.buffer.select(5)
        self.assertEqual(selection.status, WindowStatus.READY)
        self.assertEqual([item.sample_index for item in selection.samples], list(range(6)))
        self.assertEqual(selection.expected_sample_count, 6)
        self.assertEqual(selection.effective_duration_s, 5)

    def test_fractional_duration_covers_both_endpoints_using_sample_count(self):
        for index in range(3):
            self.buffer.append(sample(index), DatasetPartition.TRAIN)
        selection = self.buffer.select(1.1)
        self.assertEqual(selection.status, WindowStatus.READY)
        self.assertEqual(selection.expected_sample_count, 3)
        self.assertEqual(selection.effective_duration_s, 2)

    def test_variable_cadence_uses_time_coverage_and_configured_minimum(self):
        self.buffer.append(
            sample(0, next_expected_interval_s=5), DatasetPartition.TRAIN
        )
        self.buffer.append(
            sample(
                1,
                timestamp=START + timedelta(seconds=5),
                next_expected_interval_s=5,
            ),
            DatasetPartition.TRAIN,
        )
        selection = self.buffer.select(5, minimum_samples=2)
        self.assertEqual(selection.status, WindowStatus.READY)
        self.assertEqual(selection.expected_sample_count, 2)
        self.assertEqual([item.sample_index for item in selection.samples], [0, 1])

    def test_expected_long_idle_interval_is_not_a_gap_but_a_missed_reading_is(self):
        self.buffer.append(
            sample(0, next_expected_interval_s=5), DatasetPartition.TRAIN
        )
        self.buffer.append(
            sample(
                1,
                timestamp=START + timedelta(seconds=5),
                next_expected_interval_s=5,
            ),
            DatasetPartition.TRAIN,
        )
        self.assertEqual(
            len(self.buffer.select(5, minimum_samples=2).samples), 2
        )
        self.buffer.append(
            sample(
                2,
                timestamp=START + timedelta(seconds=15),
                next_expected_interval_s=5,
            ),
            DatasetPartition.TRAIN,
        )
        selection = self.buffer.select(5, minimum_samples=2)
        self.assertEqual(selection.status, WindowStatus.INSUFFICIENT_HISTORY)
        self.assertEqual([item.sample_index for item in selection.samples], [2])

    def test_marks_short_history_insufficient(self):
        for index in range(5):
            self.buffer.append(sample(index), DatasetPartition.TRAIN)
        selection = self.buffer.select(5)
        self.assertEqual(selection.status, WindowStatus.INSUFFICIENT_HISTORY)
        self.assertEqual(len(selection.samples), 5)

    def test_stride_limits_emissions_but_transition_can_force_selection(self):
        buffer = TemporalWindowBuffer(windowing_config(stride_s=5))
        for index in range(6):
            buffer.append(sample(index), DatasetPartition.TRAIN)
        self.assertEqual(buffer.select(5).status, WindowStatus.READY)
        buffer.append(sample(6), DatasetPartition.TRAIN)
        self.assertEqual(buffer.select(5).status, WindowStatus.NOT_DUE)
        self.assertEqual(buffer.select(5, force=True).status, WindowStatus.READY)

    def test_gap_resets_history(self):
        for index in range(6):
            self.buffer.append(sample(index), DatasetPartition.TRAIN)
        self.buffer.append(
            sample(7, timestamp=START + timedelta(seconds=20)),
            DatasetPartition.TRAIN,
        )
        self.assertEqual(
            self.buffer.select(5).status, WindowStatus.INSUFFICIENT_HISTORY
        )

    def test_run_asset_schema_and_partition_changes_do_not_mix_samples(self):
        self.buffer.append(sample(0), DatasetPartition.TRAIN)
        self.buffer.append(sample(1, run_id="run-2"), DatasetPartition.TRAIN)
        self.assertEqual(
            [item.run_id for item in self.buffer.select(1).samples], ["run-2"]
        )
        self.buffer.append(sample(2, asset_id="asset-2"), DatasetPartition.TRAIN)
        self.assertEqual(
            [item.asset_id for item in self.buffer.select(1).samples], ["asset-2"]
        )
        self.buffer.append(
            WindowSample(
                schema_version="2.0.0",
                run_id="run-1",
                sample_index=3,
                timestamp=START + timedelta(seconds=3),
                asset_id="asset-2",
                profile="solar_utility",
                observables={},
                features={},
            ),
            DatasetPartition.TRAIN,
        )
        self.assertEqual(
            [item.schema_version for item in self.buffer.select(1).samples],
            ["2.0.0"],
        )
        self.buffer.append(sample(4), DatasetPartition.TEST)
        self.assertEqual(
            [item.sample_index for item in self.buffer.select(1).samples], [4]
        )

    def test_rejects_labels_and_unknown_fields_from_inference_samples(self):
        with self.assertRaises(ValueError):
            WindowSample(
                schema_version="1.0.0",
                run_id="run-1",
                sample_index=0,
                timestamp=START,
                asset_id="asset-1",
                profile="solar_utility",
                observables={"ground_truth": {"junction_temp_c": 42}},
                features={},
            )

    def test_rejects_duplicate_or_out_of_order_samples(self):
        self.buffer.append(sample(1), DatasetPartition.TRAIN)
        with self.assertRaises(ValueError):
            self.buffer.append(sample(1), DatasetPartition.TRAIN)
        with self.assertRaises(ValueError):
            self.buffer.append(sample(0), DatasetPartition.TRAIN)


if __name__ == "__main__":
    unittest.main()
