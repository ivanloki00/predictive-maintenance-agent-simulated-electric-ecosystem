"""Deterministic evaluation metrics for held-out synthetic runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Mapping, Sequence

from .windowing import DatasetPartition


def _validate_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")


def _validate_positive(name: str, value: float, *, allow_zero: bool = False) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or (value == 0 and not allow_zero)
    ):
        comparator = "non-negative" if allow_zero else "greater than zero"
        raise ValueError(f"{name} must be finite and {comparator}")


@dataclass(frozen=True)
class AsymmetricEventCostConfig:
    false_alarm_penalty: float
    missed_event_penalty: float
    late_alarm_penalty: float
    early_detection_credit_per_hour: float
    unit: str
    rationale: str
    source: str

    def __post_init__(self) -> None:
        for name, value in (
            ("false_alarm_penalty", self.false_alarm_penalty),
            ("missed_event_penalty", self.missed_event_penalty),
            ("late_alarm_penalty", self.late_alarm_penalty),
            ("early_detection_credit_per_hour", self.early_detection_credit_per_hour),
        ):
            _validate_positive(name, value, allow_zero=True)
        if (
            not isinstance(self.unit, str)
            or not self.unit.strip()
            or not isinstance(self.rationale, str)
            or not self.rationale.strip()
            or not isinstance(self.source, str)
            or not self.source.strip()
        ):
            raise ValueError("cost unit, rationale, and source are required")


@dataclass(frozen=True)
class EvaluationConfig:
    forecast_horizon_s: float
    thermal_threshold_c: float
    alarm_cooldown_s: float
    event_costs: AsymmetricEventCostConfig | None = None

    def __post_init__(self) -> None:
        _validate_positive("forecast_horizon_s", self.forecast_horizon_s)
        if (
            isinstance(self.thermal_threshold_c, bool)
            or not isinstance(self.thermal_threshold_c, (int, float))
            or not math.isfinite(self.thermal_threshold_c)
        ):
            raise ValueError("thermal_threshold_c must be finite")
        _validate_positive("alarm_cooldown_s", self.alarm_cooldown_s, allow_zero=True)
        if self.event_costs is not None and not isinstance(
            self.event_costs, AsymmetricEventCostConfig
        ):
            raise ValueError("event_costs must be an AsymmetricEventCostConfig or None")


@dataclass(frozen=True)
class RegressionMetrics:
    sample_count: int
    mae: float
    rmse: float


def regression_metrics(
    actual: Sequence[float], predicted: Sequence[float]
) -> RegressionMetrics:
    """Calculate MAE/RMSE; invalid or misaligned samples fail explicitly."""
    if not actual or len(actual) != len(predicted):
        raise ValueError("actual and predicted must have the same non-zero length")
    squared_errors = []
    absolute_errors = []
    for index, (truth, estimate) in enumerate(zip(actual, predicted)):
        if (
            isinstance(truth, bool)
            or isinstance(estimate, bool)
            or not isinstance(truth, (int, float))
            or not isinstance(estimate, (int, float))
            or not math.isfinite(truth)
            or not math.isfinite(estimate)
        ):
            raise ValueError(f"actual and predicted values must be finite at index {index}")
        error = estimate - truth
        absolute_errors.append(abs(error))
        squared_errors.append(error * error)
    count = len(absolute_errors)
    return RegressionMetrics(
        sample_count=count,
        mae=sum(absolute_errors) / count,
        rmse=math.sqrt(sum(squared_errors) / count),
    )


@dataclass(frozen=True)
class EvaluationRun:
    run_id: str
    started_at: datetime
    ended_at: datetime
    partition: DatasetPartition

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        _validate_utc("started_at", self.started_at)
        _validate_utc("ended_at", self.ended_at)
        if self.ended_at <= self.started_at:
            raise ValueError("ended_at must be later than started_at")
        if not isinstance(self.partition, DatasetPartition):
            raise ValueError("partition must be a DatasetPartition")


@dataclass(frozen=True)
class Alarm:
    run_id: str
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        _validate_utc("timestamp", self.timestamp)


@dataclass(frozen=True)
class FailureEvent:
    run_id: str
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        _validate_utc("timestamp", self.timestamp)


@dataclass(frozen=True)
class EventMetrics:
    test_run_count: int
    observed_failure_count: int
    true_positives: int
    false_positives: int
    missed_events: int
    late_alarms: int
    operating_hours: float
    false_alarms_per_hour: float | None
    lead_times_s: tuple[float, ...]
    costs: EventCostMetrics | None = None


@dataclass(frozen=True)
class EventCostMetrics:
    false_alarm_penalty: float
    missed_event_penalty: float
    late_alarm_penalty: float
    early_detection_credit: float
    aggregate_penalty: float
    unit: str


def _group_alarms(
    alarms: Sequence[Alarm], cooldown_s: float
) -> dict[str, list[datetime]]:
    grouped: dict[str, list[datetime]] = {}
    last_alarm: dict[str, datetime] = {}
    for alarm in sorted(alarms, key=lambda item: (item.run_id, item.timestamp)):
        run_alarms = grouped.setdefault(alarm.run_id, [])
        if (
            not run_alarms
            or (alarm.timestamp - last_alarm[alarm.run_id]).total_seconds()
            > cooldown_s
        ):
            run_alarms.append(alarm.timestamp)
        last_alarm[alarm.run_id] = alarm.timestamp
    return grouped


def evaluate_events(
    runs: Sequence[EvaluationRun],
    alarms: Sequence[Alarm],
    failures: Sequence[FailureEvent],
    config: EvaluationConfig,
) -> EventMetrics:
    """Score one anticipatory alarm event per failure on test runs only."""
    test_runs = {
        run.run_id: run for run in runs if run.partition == DatasetPartition.TEST
    }
    if len(test_runs) != sum(
        run.partition == DatasetPartition.TEST for run in runs
    ):
        raise ValueError("run_id values must be unique")

    observed_failures: dict[str, datetime] = {}
    for failure in failures:
        run = test_runs.get(failure.run_id)
        if run is None:
            continue
        if failure.run_id in observed_failures:
            raise ValueError("only one failure event per run is supported")
        if not run.started_at <= failure.timestamp <= run.ended_at:
            raise ValueError("failure timestamp must fall within the observed run")
        observed_failures[failure.run_id] = failure.timestamp

    grouped_alarms = _group_alarms(
        [alarm for alarm in alarms if alarm.run_id in test_runs],
        config.alarm_cooldown_s,
    )
    operating_hours = sum(
        (run.ended_at - run.started_at).total_seconds() / 3600
        for run in test_runs.values()
    )
    true_positives = 0
    false_positives = 0
    missed_events = 0
    late_alarms = 0
    lead_times: list[float] = []

    for run_id, run in test_runs.items():
        run_alarms = grouped_alarms.get(run_id, [])
        if any(not run.started_at <= timestamp <= run.ended_at for timestamp in run_alarms):
            raise ValueError("alarm timestamp must fall within the observed run")
        failure_at = observed_failures.get(run_id)
        if failure_at is None:
            false_positives += len(run_alarms)
            continue

        eligible = [
            timestamp
            for timestamp in run_alarms
            if 0 < (failure_at - timestamp).total_seconds()
            <= config.forecast_horizon_s
        ]
        late = [timestamp for timestamp in run_alarms if timestamp >= failure_at]
        late_alarms += len(late)
        if eligible:
            first_alarm = eligible[0]
            true_positives += 1
            lead_times.append((failure_at - first_alarm).total_seconds())
            false_positives += len(run_alarms) - 1 - len(late)
        else:
            missed_events += 1
            false_positives += len(run_alarms) - len(late)

    false_alarms_per_hour = (
        false_positives / operating_hours if operating_hours > 0 else None
    )
    event_costs = config.event_costs
    cost_metrics = (
        EventCostMetrics(
            false_alarm_penalty=(
                false_positives * event_costs.false_alarm_penalty
            ),
            missed_event_penalty=(
                missed_events * event_costs.missed_event_penalty
            ),
            late_alarm_penalty=late_alarms * event_costs.late_alarm_penalty,
            early_detection_credit=(
                sum(lead_times) / 3600
                * event_costs.early_detection_credit_per_hour
            ),
            aggregate_penalty=(
                false_positives * event_costs.false_alarm_penalty
                + missed_events * event_costs.missed_event_penalty
                + late_alarms * event_costs.late_alarm_penalty
                - sum(lead_times) / 3600
                * event_costs.early_detection_credit_per_hour
            ),
            unit=event_costs.unit,
        )
        if event_costs is not None
        else None
    )
    return EventMetrics(
        test_run_count=len(test_runs),
        observed_failure_count=len(observed_failures),
        true_positives=true_positives,
        false_positives=false_positives,
        missed_events=missed_events,
        late_alarms=late_alarms,
        operating_hours=operating_hours,
        false_alarms_per_hour=false_alarms_per_hour,
        lead_times_s=tuple(lead_times),
        costs=cost_metrics,
    )


@dataclass(frozen=True)
class RULMetrics:
    scored_run_count: int
    censored_run_count: int
    mae_s: float | None


def score_rul(
    runs: Sequence[EvaluationRun],
    predicted_rul_s: Mapping[str, float],
    observed_rul_s: Mapping[str, float | None],
) -> RULMetrics:
    """Score RUL only for test runs with an observed failure; None means censored."""
    test_runs = [run for run in runs if run.partition == DatasetPartition.TEST]
    if len({run.run_id for run in test_runs}) != len(test_runs):
        raise ValueError("run_id values must be unique")

    errors: list[float] = []
    censored_count = 0
    for run in test_runs:
        if run.run_id not in observed_rul_s:
            raise ValueError(f"missing RUL label for test run {run.run_id}")
        truth = observed_rul_s[run.run_id]
        if truth is None:
            censored_count += 1
            continue
        if run.run_id not in predicted_rul_s:
            raise ValueError(f"missing RUL prediction for run {run.run_id}")
        prediction = predicted_rul_s[run.run_id]
        _validate_positive("observed RUL", truth, allow_zero=True)
        _validate_positive("predicted RUL", prediction, allow_zero=True)
        errors.append(abs(prediction - truth))
    return RULMetrics(
        scored_run_count=len(errors),
        censored_run_count=censored_count,
        mae_s=sum(errors) / len(errors) if errors else None,
    )
