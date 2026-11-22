import unittest
from datetime import datetime, timedelta, timezone

from predictive_maintenance.partitions import (
    RunDescriptor,
    assign_run_partitions,
)
from predictive_maintenance.windowing import DatasetPartition


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class RunPartitionTests(unittest.TestCase):
    def test_assigns_whole_runs_in_chronological_order(self):
        runs = [
            RunDescriptor("run-c", START + timedelta(days=2)),
            RunDescriptor("run-a", START),
            RunDescriptor("run-b", START + timedelta(days=1)),
            RunDescriptor("run-d", START + timedelta(days=3)),
        ]
        result = assign_run_partitions(
            runs, train_fraction=0.5, validation_fraction=0.25
        )
        self.assertEqual(result["run-a"], DatasetPartition.TRAIN)
        self.assertEqual(result["run-b"], DatasetPartition.TRAIN)
        self.assertEqual(result["run-c"], DatasetPartition.VALIDATION)
        self.assertEqual(result["run-d"], DatasetPartition.TEST)
        with self.assertRaises(TypeError):
            result["run-a"] = DatasetPartition.TEST

    def test_ties_are_stable_and_empty_splits_are_prevented(self):
        runs = [
            RunDescriptor(run_id, START)
            for run_id in ("run-c", "run-a", "run-b")
        ]
        result = assign_run_partitions(
            runs, train_fraction=0.8, validation_fraction=0.1
        )
        self.assertEqual(result["run-a"], DatasetPartition.TRAIN)
        self.assertEqual(result["run-b"], DatasetPartition.VALIDATION)
        self.assertEqual(result["run-c"], DatasetPartition.TEST)

    def test_rejects_duplicate_runs_too_few_runs_and_invalid_fractions(self):
        run = RunDescriptor("run-a", START)
        with self.assertRaises(ValueError):
            assign_run_partitions([run, run, RunDescriptor("run-b", START)],
                                  train_fraction=0.6, validation_fraction=0.2)
        with self.assertRaises(ValueError):
            assign_run_partitions([run, RunDescriptor("run-b", START)],
                                  train_fraction=0.6, validation_fraction=0.2)
        with self.assertRaises(ValueError):
            assign_run_partitions(
                [
                    run,
                    RunDescriptor("run-b", START + timedelta(days=1)),
                    RunDescriptor("run-c", START + timedelta(days=2)),
                ],
                train_fraction=0.8,
                validation_fraction=0.2,
            )

    def test_requires_utc_start_time(self):
        with self.assertRaises(ValueError):
            RunDescriptor("run-a", START.replace(tzinfo=None))


if __name__ == "__main__":
    unittest.main()
