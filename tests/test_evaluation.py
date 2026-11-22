import math
import unittest
from datetime import datetime, timedelta, timezone

from predictive_maintenance.evaluation import (
    Alarm,
    AsymmetricEventCostConfig,
    EvaluationConfig,
    EvaluationRun,
    FailureEvent,
    evaluate_events,
    regression_metrics,
    score_rul,
)
from predictive_maintenance.windowing import DatasetPartition


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def evaluation_run(
    run_id,
    duration_s,
    partition=DatasetPartition.TEST,
):
    return EvaluationRun(
        run_id,
        START,
        START + timedelta(seconds=duration_s),
        partition,
    )


class RegressionMetricTests(unittest.TestCase):
    def test_calculates_mae_and_rmse(self):
        result = regression_metrics([1, 2, 3], [2, 2, 5])
        self.assertEqual(result.sample_count, 3)
        self.assertAlmostEqual(result.mae, 1)
        self.assertAlmostEqual(result.rmse, math.sqrt(5 / 3))

    def test_rejects_misaligned_empty_and_nonfinite_data(self):
        with self.assertRaises(ValueError):
            regression_metrics([], [])
        with self.assertRaises(ValueError):
            regression_metrics([1], [1, 2])
        with self.assertRaises(ValueError):
            regression_metrics([float("nan")], [1])


class EventMetricTests(unittest.TestCase):
    def setUp(self):
        self.config = EvaluationConfig(
            forecast_horizon_s=20,
            thermal_threshold_c=100,
            alarm_cooldown_s=5,
        )

    def test_groups_alarms_and_scores_test_events_with_lead_time(self):
        runs = [
            evaluation_run("run-failure", 110),
            evaluation_run("run-healthy", 3600),
            evaluation_run("run-training", 100, DatasetPartition.TRAIN),
        ]
        alarms = [
            Alarm("run-failure", START + timedelta(seconds=80)),
            Alarm("run-failure", START + timedelta(seconds=84)),
            Alarm("run-failure", START + timedelta(seconds=88)),
            Alarm("run-failure", START + timedelta(seconds=95)),
            Alarm("run-failure", START + timedelta(seconds=101)),
            Alarm("run-healthy", START + timedelta(seconds=1800)),
            Alarm("run-training", START + timedelta(seconds=50)),
        ]
        failures = [
            FailureEvent("run-failure", START + timedelta(seconds=100)),
            FailureEvent("run-training", START + timedelta(seconds=80)),
        ]
        result = evaluate_events(
            runs,
            alarms,
            failures,
            self.config,
        )
        self.assertEqual(result.test_run_count, 2)
        self.assertEqual(result.observed_failure_count, 1)
        self.assertEqual(result.true_positives, 1)
        self.assertEqual(result.false_positives, 2)
        self.assertEqual(result.missed_events, 0)
        self.assertEqual(result.late_alarms, 1)
        self.assertEqual(result.lead_times_s, (20,))
        self.assertAlmostEqual(result.false_alarms_per_hour, 2 / (3710 / 3600))

    def test_asymmetric_costs_are_only_aggregated_with_explicit_justification(self):
        config = EvaluationConfig(
            forecast_horizon_s=20,
            thermal_threshold_c=100,
            alarm_cooldown_s=5,
            event_costs=AsymmetricEventCostConfig(
                false_alarm_penalty=2,
                missed_event_penalty=10,
                late_alarm_penalty=4,
                early_detection_credit_per_hour=1,
                unit="operator_cost_units",
                rationale="Illustrative relative weights for a controlled test.",
                source="synthetic test configuration",
            ),
        )
        result = evaluate_events(
            [
                evaluation_run("run-failure", 110),
                evaluation_run("run-healthy", 3600),
            ],
            [
                Alarm("run-failure", START + timedelta(seconds=80)),
                Alarm("run-failure", START + timedelta(seconds=101)),
                Alarm("run-healthy", START + timedelta(seconds=1800)),
            ],
            [FailureEvent("run-failure", START + timedelta(seconds=100))],
            config,
        )
        self.assertIsNotNone(result.costs)
        self.assertEqual(result.costs.false_alarm_penalty, 2)
        self.assertEqual(result.costs.late_alarm_penalty, 4)
        self.assertAlmostEqual(result.costs.early_detection_credit, 20 / 3600)
        self.assertAlmostEqual(
            result.costs.aggregate_penalty, 6 - 20 / 3600
        )

    def test_cost_configuration_requires_provenance(self):
        with self.assertRaises(ValueError):
            AsymmetricEventCostConfig(1, 2, 3, 4, "units", "", "source")

    def test_late_alarm_is_a_miss_not_an_early_true_positive(self):
        run = evaluation_run("run-1", 100)
        result = evaluate_events(
            [run],
            [Alarm("run-1", START + timedelta(seconds=50))],
            [FailureEvent("run-1", START + timedelta(seconds=50))],
            self.config,
        )
        self.assertEqual(result.true_positives, 0)
        self.assertEqual(result.missed_events, 1)
        self.assertEqual(result.late_alarms, 1)
        self.assertEqual(result.false_positives, 0)
        self.assertEqual(result.lead_times_s, ())

    def test_alarms_beyond_horizon_are_false_alarms_and_events_are_missed(self):
        run = evaluation_run("run-1", 100)
        result = evaluate_events(
            [run],
            [Alarm("run-1", START + timedelta(seconds=50))],
            [FailureEvent("run-1", START + timedelta(seconds=90))],
            self.config,
        )
        self.assertEqual(result.true_positives, 0)
        self.assertEqual(result.missed_events, 1)
        self.assertEqual(result.false_positives, 1)

    def test_rejects_multiple_failures_and_out_of_run_events(self):
        run = evaluation_run("run-1", 100)
        with self.assertRaises(ValueError):
            evaluate_events(
                [run],
                [],
                [
                    FailureEvent("run-1", START + timedelta(seconds=20)),
                    FailureEvent("run-1", START + timedelta(seconds=30)),
                ],
                self.config,
            )
        with self.assertRaises(ValueError):
            evaluate_events(
                [run],
                [Alarm("run-1", START + timedelta(seconds=101))],
                [],
                self.config,
            )


class RULMetricTests(unittest.TestCase):
    def test_censored_runs_are_not_scored_as_zero_rul(self):
        runs = [
            evaluation_run("run-failed", 100),
            evaluation_run("run-censored", 100),
            evaluation_run("run-training", 100, DatasetPartition.TRAIN),
        ]
        result = score_rul(
            runs,
            {"run-failed": 120, "run-censored": 999, "run-training": 0},
            {"run-failed": 100, "run-censored": None, "run-training": 0},
        )
        self.assertEqual(result.scored_run_count, 1)
        self.assertEqual(result.censored_run_count, 1)
        self.assertEqual(result.mae_s, 20)

    def test_returns_no_rul_score_when_test_runs_are_censored(self):
        result = score_rul(
            [evaluation_run("run-censored", 100)],
            {},
            {"run-censored": None},
        )
        self.assertEqual(result.scored_run_count, 0)
        self.assertEqual(result.censored_run_count, 1)
        self.assertIsNone(result.mae_s)

    def test_requires_prediction_for_an_observed_test_failure(self):
        with self.assertRaises(ValueError):
            score_rul(
                [evaluation_run("run-failed", 100)],
                {},
                {"run-failed": 100},
            )

    def test_requires_explicit_censoring_label_for_each_test_run(self):
        with self.assertRaises(ValueError):
            score_rul([evaluation_run("run-1", 100)], {}, {})


if __name__ == "__main__":
    unittest.main()
