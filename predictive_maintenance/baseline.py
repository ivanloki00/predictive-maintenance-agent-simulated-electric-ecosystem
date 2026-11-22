"""Causal RC-inspired junction-temperature baseline and held-out evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from types import MappingProxyType
from typing import Mapping

from .evaluation import (
    Alarm,
    EvaluationConfig,
    EvaluationRun,
    EventMetrics,
    FailureEvent,
    RegressionMetrics,
    evaluate_events,
    regression_metrics,
)
from .simulator import SyntheticDataset
from .windowing import (
    DatasetPartition,
    NBRegimeClassifier,
    NBRegimeConfig,
    Regime,
    SolarRegimeClassifier,
    SolarRegimeConfig,
)


@dataclass(frozen=True)
class RCBaselineConfig:
    nominal_power_kw: Mapping[str, float]
    temperature_rise_at_full_load_c: float
    thermal_time_constant_s: float

    def __post_init__(self) -> None:
        if not self.nominal_power_kw:
            raise ValueError("nominal_power_kw must define at least one profile")
        for profile, value in self.nominal_power_kw.items():
            if profile not in {"solar_utility", "ev_nb"}:
                raise ValueError(f"unsupported profile: {profile}")
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"nominal power for {profile} must be positive")
        for name, value in (
            ("temperature_rise_at_full_load_c", self.temperature_rise_at_full_load_c),
            ("thermal_time_constant_s", self.thermal_time_constant_s),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and greater than zero")


class RCTemperatureBaseline:
    """Estimate current junction temperature from measured telemetry only."""

    def __init__(self, config: RCBaselineConfig) -> None:
        self._config = config
        self._previous_timestamp: datetime | None = None
        self._estimate: float | None = None

    def reset(self) -> None:
        self._previous_timestamp = None
        self._estimate = None

    def estimate(self, sample: Mapping[str, object]) -> float:
        profile = sample.get("profile")
        if profile not in self._config.nominal_power_kw:
            raise ValueError("sample profile has no configured nominal power")
        timestamp = self._parse_timestamp(sample.get("timestamp"))
        observables = sample.get("observables")
        if not isinstance(observables, Mapping):
            raise ValueError("sample observables must be a mapping")

        heatsink = observables.get("heatsink_temp_c")
        if (
            isinstance(heatsink, bool)
            or not isinstance(heatsink, (int, float))
            or not math.isfinite(heatsink)
        ):
            raise ValueError("a finite heatsink_temp_c measurement is required")
        nominal_power = self._config.nominal_power_kw[profile]
        if profile == "solar_utility":
            voltage = observables.get("dc_bus_voltage_v")
            current = observables.get("dc_bus_current_a")
            if (
                isinstance(voltage, bool)
                or isinstance(current, bool)
                or not isinstance(voltage, (int, float))
                or not isinstance(current, (int, float))
                or not math.isfinite(voltage)
                or not math.isfinite(current)
            ):
                raise ValueError("finite DC bus voltage and current are required")
            load_power_kw = max(0.0, voltage * current / 1000)
        else:
            load_power = observables.get("ev_power_kw")
            if load_power is None:
                voltage = observables.get("dc_bus_voltage_v")
                current = observables.get("dc_bus_current_a")
                if (
                    isinstance(voltage, bool)
                    or isinstance(current, bool)
                    or not isinstance(voltage, (int, float))
                    or not isinstance(current, (int, float))
                    or not math.isfinite(voltage)
                    or not math.isfinite(current)
                ):
                    raise ValueError(
                        "ev_power_kw or finite DC bus voltage and current are required"
                    )
                load_power = voltage * current / 1000
            if (
                isinstance(load_power, bool)
                or not isinstance(load_power, (int, float))
                or not math.isfinite(load_power)
            ):
                raise ValueError("a finite ev_power_kw measurement is required")
            load_power_kw = max(0.0, load_power)

        target = heatsink + self._config.temperature_rise_at_full_load_c * min(
            1.0, load_power_kw / nominal_power
        )
        if self._previous_timestamp is None:
            estimate = target
        else:
            elapsed_s = (timestamp - self._previous_timestamp).total_seconds()
            if elapsed_s <= 0:
                raise ValueError("sample timestamps must be strictly increasing")
            alpha = 1 - math.exp(-elapsed_s / self._config.thermal_time_constant_s)
            if self._estimate is None:
                raise RuntimeError("baseline state is inconsistent")
            estimate = self._estimate + alpha * (target - self._estimate)
        self._estimate = estimate
        self._previous_timestamp = timestamp
        return estimate

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        if not isinstance(value, str):
            raise ValueError("sample timestamp must be an ISO 8601 UTC string")
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("sample timestamp must be valid ISO 8601") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
            raise ValueError("sample timestamp must be UTC")
        return timestamp


@dataclass(frozen=True)
class BaselineEvaluation:
    test_run_count: int
    temperature_metrics: RegressionMetrics
    forecast_temperature_metrics: RegressionMetrics | None
    temperature_metrics_by_profile: Mapping[str, RegressionMetrics]
    temperature_metrics_by_scenario: Mapping[str, RegressionMetrics]
    temperature_metrics_by_regime: Mapping[str, RegressionMetrics]
    forecast_temperature_metrics_by_profile: Mapping[str, RegressionMetrics]
    forecast_temperature_metrics_by_scenario: Mapping[str, RegressionMetrics]
    forecast_temperature_metrics_by_regime: Mapping[str, RegressionMetrics]
    event_metrics: EventMetrics
    event_metrics_by_profile: Mapping[str, EventMetrics]
    event_metrics_by_scenario: Mapping[str, EventMetrics]


def _classify_regimes(
    samples: list[dict[str, object]],
    profile: str,
    solar_config: SolarRegimeConfig | None,
    nb_config: NBRegimeConfig | None,
) -> tuple[str, ...]:
    if solar_config is None and nb_config is None:
        return (Regime.UNKNOWN.value,) * len(samples)
    if solar_config is None or nb_config is None:
        raise ValueError("both solar and NB regime configurations are required")
    if profile == "solar_utility":
        classifier = SolarRegimeClassifier(solar_config)
        regimes = []
        for sample in samples:
            observables = sample.get("observables")
            irradiance = (
                observables.get("irradiance_w_m2")
                if isinstance(observables, Mapping)
                else None
            )
            if isinstance(irradiance, bool) or not isinstance(irradiance, (int, float)):
                irradiance = None
            regimes.append(
                classifier.update(
                    RCTemperatureBaseline._parse_timestamp(sample.get("timestamp")),
                    irradiance,
                ).value
            )
        return tuple(regimes)
    if profile == "ev_nb":
        classifier = NBRegimeClassifier(nb_config)
        regimes = []
        for sample in samples:
            observables = sample.get("observables")
            if not isinstance(observables, Mapping):
                raise ValueError("sample observables must be a mapping")
            session_active = observables.get("ev_session_active")
            power = observables.get("ev_power_kw")
            if isinstance(power, bool) or not isinstance(power, (int, float)):
                power = None
            regimes.append(
                classifier.update(
                    RCTemperatureBaseline._parse_timestamp(sample.get("timestamp")),
                    session_active if isinstance(session_active, bool) else None,
                    power,
                ).value
            )
        return tuple(regimes)
    raise ValueError(f"unsupported profile: {profile}")


def _metrics_if_available(
    actual: list[float], predicted: list[float]
) -> RegressionMetrics | None:
    if not actual:
        return None
    return regression_metrics(actual, predicted)


def evaluate_rc_baseline(
    dataset: SyntheticDataset,
    *,
    baseline_config: RCBaselineConfig,
    evaluation_config: EvaluationConfig,
    solar_regime_config: SolarRegimeConfig | None = None,
    nb_regime_config: NBRegimeConfig | None = None,
) -> BaselineEvaluation:
    """Evaluate the RC baseline only on test runs, joining labels outside inference."""
    manifest_runs = dataset.manifest.get("runs")
    if not isinstance(manifest_runs, list) or not manifest_runs:
        raise ValueError("dataset manifest must contain runs")
    partitions: dict[str, DatasetPartition] = {}
    scenarios: dict[str, str] = {}
    for run in manifest_runs:
        if not isinstance(run, dict) or not isinstance(run.get("run_id"), str):
            raise ValueError("invalid run entry in manifest")
        try:
            partition = DatasetPartition(run["eval_group"])
        except (ValueError, KeyError) as exc:
            raise ValueError("manifest run has an invalid eval_group") from exc
        if run["run_id"] in partitions:
            raise ValueError("manifest contains duplicate run_id values")
        partitions[run["run_id"]] = partition
        scenario = run.get("scenario")
        if not isinstance(scenario, str) or not scenario:
            raise ValueError("manifest run has an invalid scenario")
        scenarios[run["run_id"]] = scenario

    label_by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    for label in dataset.labels:
        key = (label["run_id"], label["asset_id"], label["timestamp"])
        if key in label_by_key:
            raise ValueError("duplicate label key")
        label_by_key[key] = label

    telemetry_by_run: dict[str, list[dict[str, object]]] = {}
    for sample in dataset.telemetry:
        run_id = sample["run_id"]
        if run_id not in partitions:
            raise ValueError("telemetry contains a run missing from manifest")
        telemetry_by_run.setdefault(run_id, []).append(sample)

    test_actual: list[float] = []
    test_estimated: list[float] = []
    forecast_actual: list[float] = []
    forecast_estimated: list[float] = []
    actual_by_profile: dict[str, list[float]] = {}
    estimated_by_profile: dict[str, list[float]] = {}
    forecast_actual_by_profile: dict[str, list[float]] = {}
    forecast_estimated_by_profile: dict[str, list[float]] = {}
    actual_by_scenario: dict[str, list[float]] = {}
    estimated_by_scenario: dict[str, list[float]] = {}
    forecast_actual_by_scenario: dict[str, list[float]] = {}
    forecast_estimated_by_scenario: dict[str, list[float]] = {}
    actual_by_regime: dict[str, list[float]] = {}
    estimated_by_regime: dict[str, list[float]] = {}
    forecast_actual_by_regime: dict[str, list[float]] = {}
    forecast_estimated_by_regime: dict[str, list[float]] = {}
    alarms: list[Alarm] = []
    failures: list[FailureEvent] = []
    evaluation_runs: list[EvaluationRun] = []
    profile_by_run: dict[str, str] = {}
    for run_id, samples in telemetry_by_run.items():
        samples.sort(key=lambda item: item["timestamp"])
        if not samples:
            raise ValueError(f"run {run_id} has no telemetry")
        timestamps = [
            RCTemperatureBaseline._parse_timestamp(sample["timestamp"])
            for sample in samples
        ]
        run_labels: list[dict[str, object]] = []
        for sample in samples:
            key = (run_id, sample["asset_id"], sample["timestamp"])
            label = label_by_key.get(key)
            if label is None:
                raise ValueError(f"missing ground-truth label for {key}")
            run_labels.append(label)
        ground_truth_events = {
            entry["ground_truth"]["failure_time_utc"]
            for entry in run_labels
            if entry["ground_truth"]["failure_time_utc"] is not None
        }
        if len(ground_truth_events) > 1:
            raise ValueError(f"run {run_id} has inconsistent failure labels")

        baseline = RCTemperatureBaseline(baseline_config)
        estimated = [baseline.estimate(sample) for sample in samples]
        partition = partitions[run_id]
        if partition != DatasetPartition.TEST:
            continue
        profile = samples[0]["profile"]
        if not isinstance(profile, str):
            raise ValueError(f"run {run_id} has an invalid profile")
        scenario = scenarios[run_id]
        regimes = _classify_regimes(
            samples, profile, solar_regime_config, nb_regime_config
        )
        profile_by_run[run_id] = profile
        evaluation_runs.append(
            EvaluationRun(run_id, timestamps[0], timestamps[-1], partition)
        )
        actual_by_profile.setdefault(profile, [])
        estimated_by_profile.setdefault(profile, [])
        forecast_actual_by_profile.setdefault(profile, [])
        forecast_estimated_by_profile.setdefault(profile, [])
        actual_by_scenario.setdefault(scenario, [])
        estimated_by_scenario.setdefault(scenario, [])
        forecast_actual_by_scenario.setdefault(scenario, [])
        forecast_estimated_by_scenario.setdefault(scenario, [])
        timestamp_indices = {timestamp: index for index, timestamp in enumerate(timestamps)}
        for sample, label, estimate, timestamp, regime in zip(
            samples, run_labels, estimated, timestamps, regimes
        ):
            truth = label["ground_truth"]["junction_temp_c"]
            if (
                isinstance(truth, bool)
                or not isinstance(truth, (int, float))
                or not math.isfinite(truth)
            ):
                raise ValueError("junction temperature ground truth must be finite")
            test_actual.append(truth)
            test_estimated.append(estimate)
            actual_by_profile[profile].append(truth)
            estimated_by_profile[profile].append(estimate)
            actual_by_scenario[scenario].append(truth)
            estimated_by_scenario[scenario].append(estimate)
            actual_by_regime.setdefault(regime, []).append(truth)
            estimated_by_regime.setdefault(regime, []).append(estimate)
            future_index = timestamp_indices.get(
                timestamp + timedelta(seconds=evaluation_config.forecast_horizon_s)
            )
            if future_index is not None:
                future_truth = run_labels[future_index]["ground_truth"][
                    "junction_temp_c"
                ]
                if (
                    isinstance(future_truth, bool)
                    or not isinstance(future_truth, (int, float))
                    or not math.isfinite(future_truth)
                ):
                    raise ValueError(
                        "future junction temperature ground truth must be finite"
                    )
                forecast_actual.append(future_truth)
                forecast_estimated.append(estimate)
                forecast_actual_by_profile[profile].append(future_truth)
                forecast_estimated_by_profile[profile].append(estimate)
                forecast_actual_by_scenario[scenario].append(future_truth)
                forecast_estimated_by_scenario[scenario].append(estimate)
                forecast_actual_by_regime.setdefault(regime, []).append(future_truth)
                forecast_estimated_by_regime.setdefault(regime, []).append(estimate)
            if estimate >= evaluation_config.thermal_threshold_c:
                alarms.append(Alarm(run_id, timestamp))
        if ground_truth_events:
            failure_at = datetime.fromisoformat(
                next(iter(ground_truth_events)).replace("Z", "+00:00")
            )
            failures.append(FailureEvent(run_id, failure_at))

    if not evaluation_runs:
        raise ValueError("dataset has no test runs")
    event_metrics = evaluate_events(
        evaluation_runs, alarms, failures, evaluation_config
    )
    event_metrics_by_profile = {
        profile: evaluate_events(
            [run for run in evaluation_runs if profile_by_run[run.run_id] == profile],
            [
                alarm
                for alarm in alarms
                if profile_by_run.get(alarm.run_id) == profile
            ],
            [
                failure
                for failure in failures
                if profile_by_run.get(failure.run_id) == profile
            ],
            evaluation_config,
        )
        for profile in sorted(set(profile_by_run.values()))
    }
    event_metrics_by_scenario = {
        scenario: evaluate_events(
            [run for run in evaluation_runs if scenarios[run.run_id] == scenario],
            [
                alarm
                for alarm in alarms
                if scenarios.get(alarm.run_id) == scenario
            ],
            [
                failure
                for failure in failures
                if scenarios.get(failure.run_id) == scenario
            ],
            evaluation_config,
        )
        for scenario in sorted(
            {scenarios[run.run_id] for run in evaluation_runs}
        )
    }
    forecast_metrics_by_profile = {
        profile: regression_metrics(
            forecast_actual_by_profile[profile],
            forecast_estimated_by_profile[profile],
        )
        for profile in sorted(forecast_actual_by_profile)
        if forecast_actual_by_profile[profile]
    }
    forecast_metrics_by_scenario = {
        scenario: regression_metrics(
            forecast_actual_by_scenario[scenario],
            forecast_estimated_by_scenario[scenario],
        )
        for scenario in sorted(forecast_actual_by_scenario)
        if forecast_actual_by_scenario[scenario]
    }
    forecast_metrics_by_regime = {
        regime: regression_metrics(
            forecast_actual_by_regime[regime],
            forecast_estimated_by_regime[regime],
        )
        for regime in sorted(forecast_actual_by_regime)
        if forecast_actual_by_regime[regime]
    }
    return BaselineEvaluation(
        test_run_count=len(evaluation_runs),
        temperature_metrics=regression_metrics(test_actual, test_estimated),
        forecast_temperature_metrics=_metrics_if_available(
            forecast_actual, forecast_estimated
        ),
        temperature_metrics_by_profile=MappingProxyType(
            {
                profile: regression_metrics(
                    actual_by_profile[profile], estimated_by_profile[profile]
                )
                for profile in sorted(actual_by_profile)
            }
        ),
        temperature_metrics_by_scenario=MappingProxyType(
            {
                scenario: regression_metrics(
                    actual_by_scenario[scenario], estimated_by_scenario[scenario]
                )
                for scenario in sorted(actual_by_scenario)
            }
        ),
        temperature_metrics_by_regime=MappingProxyType(
            {
                regime: regression_metrics(
                    actual_by_regime[regime], estimated_by_regime[regime]
                )
                for regime in sorted(actual_by_regime)
            }
        ),
        forecast_temperature_metrics_by_profile=MappingProxyType(
            forecast_metrics_by_profile
        ),
        forecast_temperature_metrics_by_scenario=MappingProxyType(
            forecast_metrics_by_scenario
        ),
        forecast_temperature_metrics_by_regime=MappingProxyType(
            forecast_metrics_by_regime
        ),
        event_metrics=event_metrics,
        event_metrics_by_profile=MappingProxyType(event_metrics_by_profile),
        event_metrics_by_scenario=MappingProxyType(event_metrics_by_scenario),
    )

