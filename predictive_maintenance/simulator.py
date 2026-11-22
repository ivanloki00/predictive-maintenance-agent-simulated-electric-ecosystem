"""Reproducible, synthetic Freesun/NB telemetry with isolated ground truth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import json
import math
from pathlib import Path
import random
from typing import Sequence
import uuid

from .partitions import RunDescriptor, assign_run_partitions
from .windowing import DatasetPartition


class DegradationMode(str, Enum):
    NONE = "none"
    IGBT_THERMAL_FATIGUE = "igbt_thermal_fatigue"
    DC_LINK_CAPACITOR = "dc_link_capacitor"
    INSULATION = "insulation"
    PHASE_IMBALANCE = "phase_imbalance"


@dataclass(frozen=True)
class SyntheticMilestoneConfig:
    predictive_warning_damage_fraction: float = 0.6
    synthetic_protection_damage_fraction: float = 0.85
    end_of_life_damage_fraction: float = 1.0

    def __post_init__(self) -> None:
        fractions = (
            self.predictive_warning_damage_fraction,
            self.synthetic_protection_damage_fraction,
            self.end_of_life_damage_fraction,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in fractions
        ):
            raise ValueError("milestone damage fractions must be finite numbers")
        if not (
            0 <= self.predictive_warning_damage_fraction
            < self.synthetic_protection_damage_fraction
            < self.end_of_life_damage_fraction
            <= 1
        ):
            raise ValueError(
                "milestones must satisfy 0 <= warning < protection < end_of_life <= 1"
            )


@dataclass(frozen=True)
class SyntheticRunConfig:
    run_id: str
    asset_id: str
    profile: str
    seed: int
    started_at: datetime
    duration_s: int
    physical_step_ms: int
    sampling_period_ms: int
    prediction_horizon_s: float
    degradation_mode: DegradationMode
    degradation_onset_fraction: float
    ambient_temperature_c: float
    sensor_noise_stddev: float
    nominal_power_kw: float
    thermal_time_constant_s: float
    temperature_rise_at_full_load_c: float
    insulation_baseline_megaohm: float
    esr_baseline_mohm: float
    thermal_failure_threshold_c: float
    esr_failure_ratio: float
    insulation_failure_megaohm: float
    nb_idle_sampling_period_ms: int | None = None
    milestones: SyntheticMilestoneConfig = SyntheticMilestoneConfig()
    esr_growth_exponent: float = 2.0
    humidity_baseline_pct: float = 58.0
    humidity_daily_amplitude_pct: float = 24.0
    humidity_reference_pct: float = 60.0
    phase_imbalance_at_full_damage_pct: float = 12.0
    phase_imbalance_failure_threshold_pct: float = 8.0

    def __post_init__(self) -> None:
        try:
            parsed_run_id = uuid.UUID(self.run_id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("run_id must be a UUID v4") from exc
        if parsed_run_id.version != 4:
            raise ValueError("run_id must be a UUID v4")
        if not self.asset_id:
            raise ValueError("asset_id is required")
        if self.profile not in {"solar_utility", "ev_nb"}:
            raise ValueError("profile must be solar_utility or ev_nb")
        if (
            not isinstance(self.started_at, datetime)
            or self.started_at.tzinfo is None
            or self.started_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("started_at must be a timezone-aware UTC datetime")
        if (
            isinstance(self.duration_s, bool)
            or not isinstance(self.duration_s, int)
            or self.duration_s <= 0
            or isinstance(self.physical_step_ms, bool)
            or not isinstance(self.physical_step_ms, int)
            or self.physical_step_ms <= 0
            or isinstance(self.sampling_period_ms, bool)
            or not isinstance(self.sampling_period_ms, int)
            or self.sampling_period_ms <= 0
            or (
                self.nb_idle_sampling_period_ms is not None
                and (
                    isinstance(self.nb_idle_sampling_period_ms, bool)
                    or not isinstance(self.nb_idle_sampling_period_ms, int)
                    or self.nb_idle_sampling_period_ms <= 0
                )
            )
        ):
            raise ValueError(
                "duration_s and telemetry intervals must be positive integers"
            )
        if (
            self.sampling_period_ms % self.physical_step_ms
            or (
                self.nb_idle_sampling_period_ms is not None
                and self.nb_idle_sampling_period_ms % self.physical_step_ms
            )
            or 1000 % self.physical_step_ms
            or (self.duration_s * 1000) % self.physical_step_ms
        ):
            raise ValueError(
                "physical_step_ms must divide telemetry intervals, run duration, and one second"
            )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if self.nb_idle_sampling_period_ms is not None and self.profile != "ev_nb":
            raise ValueError(
                "nb_idle_sampling_period_ms is only valid for the ev_nb profile"
            )
        if (
            self.nb_idle_sampling_period_ms is None
            and (self.duration_s * 1000) % self.sampling_period_ms
        ):
            raise ValueError(
                "duration_s must be divisible by sampling_period_ms in fixed-cadence mode"
            )
        for name, value in (
            ("prediction_horizon_s", self.prediction_horizon_s),
            ("ambient_temperature_c", self.ambient_temperature_c),
            ("nominal_power_kw", self.nominal_power_kw),
            ("thermal_time_constant_s", self.thermal_time_constant_s),
            ("temperature_rise_at_full_load_c", self.temperature_rise_at_full_load_c),
            ("insulation_baseline_megaohm", self.insulation_baseline_megaohm),
            ("esr_baseline_mohm", self.esr_baseline_mohm),
            ("thermal_failure_threshold_c", self.thermal_failure_threshold_c),
            ("esr_failure_ratio", self.esr_failure_ratio),
            ("insulation_failure_megaohm", self.insulation_failure_megaohm),
            ("esr_growth_exponent", self.esr_growth_exponent),
            ("humidity_baseline_pct", self.humidity_baseline_pct),
            ("humidity_reference_pct", self.humidity_reference_pct),
            (
                "phase_imbalance_at_full_damage_pct",
                self.phase_imbalance_at_full_damage_pct,
            ),
            (
                "phase_imbalance_failure_threshold_pct",
                self.phase_imbalance_failure_threshold_pct,
            ),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and greater than zero")
        if (
            isinstance(self.humidity_daily_amplitude_pct, bool)
            or not isinstance(self.humidity_daily_amplitude_pct, (int, float))
            or not math.isfinite(self.humidity_daily_amplitude_pct)
            or self.humidity_daily_amplitude_pct < 0
            or self.humidity_baseline_pct - self.humidity_daily_amplitude_pct < 0
            or self.humidity_baseline_pct + self.humidity_daily_amplitude_pct > 100
        ):
            raise ValueError(
                "humidity baseline and amplitude must stay within 0 to 100 percent"
            )
        if (
            isinstance(self.degradation_onset_fraction, bool)
            or not isinstance(self.degradation_onset_fraction, (int, float))
            or not math.isfinite(self.degradation_onset_fraction)
            or not 0 <= self.degradation_onset_fraction < 1
        ):
            raise ValueError("degradation_onset_fraction must be in [0, 1)")
        if (
            isinstance(self.sensor_noise_stddev, bool)
            or not isinstance(self.sensor_noise_stddev, (int, float))
            or not math.isfinite(self.sensor_noise_stddev)
            or self.sensor_noise_stddev < 0
        ):
            raise ValueError("sensor_noise_stddev must be finite and non-negative")
        if not isinstance(self.degradation_mode, DegradationMode):
            raise ValueError("degradation_mode must be a DegradationMode")
        if not isinstance(self.milestones, SyntheticMilestoneConfig):
            raise ValueError("milestones must be a SyntheticMilestoneConfig")


@dataclass(frozen=True)
class SimulatedRun:
    config: SyntheticRunConfig
    telemetry: tuple[dict[str, object], ...]
    labels: tuple[dict[str, object], ...]
    event_onset_utc: datetime | None
    failure_time_utc: datetime | None


@dataclass(frozen=True)
class SyntheticDataset:
    telemetry: tuple[dict[str, object], ...]
    labels: tuple[dict[str, object], ...]
    manifest: dict[str, object]


def _noisy(rng: random.Random, value: float, noise: float) -> float:
    return round(value + rng.gauss(0, noise), 6)


def _nb_session_active(config: SyntheticRunConfig, elapsed_s: float) -> bool:
    cycle_s = max(60.0, min(600.0, config.duration_s / 3))
    return elapsed_s % cycle_s < cycle_s * 0.65


def _emission_schedule(config: SyntheticRunConfig) -> tuple[tuple[int, int | None], ...]:
    """Return emission times and expected gaps; None marks the first sample."""
    duration_ms = config.duration_s * 1000
    elapsed_ms = 0
    schedule: list[tuple[int, int | None]] = [(0, None)]
    while elapsed_ms < duration_ms:
        interval_ms = config.sampling_period_ms
        if (
            config.profile == "ev_nb"
            and config.nb_idle_sampling_period_ms is not None
            and not _nb_session_active(config, elapsed_ms / 1000)
        ):
            interval_ms = config.nb_idle_sampling_period_ms
        next_elapsed_ms = elapsed_ms + interval_ms
        if next_elapsed_ms > duration_ms:
            break
        schedule.append((next_elapsed_ms, interval_ms))
        elapsed_ms = next_elapsed_ms
    return tuple(schedule)


def _milestone_timestamp(
    config: SyntheticRunConfig, damage_fraction: float
) -> datetime | None:
    if config.degradation_mode == DegradationMode.NONE:
        return None
    onset_s = config.duration_s * config.degradation_onset_fraction
    elapsed_s = onset_s + damage_fraction * (config.duration_s - onset_s)
    return config.started_at + timedelta(seconds=elapsed_s)


def _timestamp_text(timestamp: datetime | None) -> str | None:
    if timestamp is None:
        return None
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _synthetic_parameter(value: object, unit: str, meaning: str) -> dict[str, object]:
    return {
        "value": value,
        "unit": unit,
        "meaning": meaning,
        "source": "synthetic scenario configuration",
        "confidence": "low",
        "status": "synthetic_unvalidated",
    }


def simulate_run(config: SyntheticRunConfig) -> SimulatedRun:
    """Generate one deterministic run; labels are never included in telemetry."""
    rng = random.Random(config.seed)
    physical_step_s = config.physical_step_ms / 1000
    schedule = _emission_schedule(config)
    onset_time = (
        config.duration_s * config.degradation_onset_fraction
        if config.degradation_mode != DegradationMode.NONE
        else None
    )
    event_onset = (
        config.started_at + timedelta(seconds=onset_time)
        if onset_time is not None
        else None
    )
    warning_time = _milestone_timestamp(
        config, config.milestones.predictive_warning_damage_fraction
    )
    protection_time = _milestone_timestamp(
        config, config.milestones.synthetic_protection_damage_fraction
    )
    end_of_life_time = _milestone_timestamp(
        config, config.milestones.end_of_life_damage_fraction
    )
    max_failure_temperature = config.thermal_failure_threshold_c
    failure_time: datetime | None = None
    telemetry: list[dict[str, object]] = []
    labels: list[dict[str, object]] = []
    junction_temp = config.ambient_temperature_c
    heatsink_temp = config.ambient_temperature_c
    previous_timestamp: datetime | None = None
    previous_humidity_pct: float | None = None
    humidity_exposure_pct_s = 0.0

    for sample_index, (elapsed_ms, expected_interval_ms) in enumerate(schedule):
        elapsed_s = elapsed_ms / 1000
        integration_steps = (
            (expected_interval_ms or config.sampling_period_ms)
            // config.physical_step_ms
        )
        timestamp = config.started_at + timedelta(seconds=elapsed_s)
        if onset_time is None or elapsed_s < onset_time:
            damage = 0.0
        else:
            damage = min(
                1.0,
                (elapsed_s - onset_time) / (config.duration_s - onset_time),
            )

        day_phase = (elapsed_s / config.duration_s) * math.pi
        ambient = config.ambient_temperature_c + 3 * math.sin(day_phase * 2)
        humidity = (
            config.humidity_baseline_pct
            + config.humidity_daily_amplitude_pct * math.sin(day_phase * 2 + 1)
        )
        if onset_time is not None and previous_timestamp is not None:
            previous_elapsed_s = (
                previous_timestamp - config.started_at
            ).total_seconds()
            exposure_start_s = max(previous_elapsed_s, onset_time)
            exposure_duration_s = max(0.0, elapsed_s - exposure_start_s)
            if exposure_duration_s > 0 and previous_humidity_pct is not None:
                start_humidity = (
                    previous_humidity_pct
                    if previous_elapsed_s >= onset_time
                    else humidity
                )
                humidity_exposure_pct_s += (
                    (start_humidity + humidity) / 2 * exposure_duration_s
                )
        degradation_elapsed_s = (
            max(0.0, elapsed_s - onset_time) if onset_time is not None else 0.0
        )
        humidity_exposure_factor = (
            min(
                1.5,
                humidity_exposure_pct_s
                / degradation_elapsed_s
                / config.humidity_reference_pct,
            )
            if degradation_elapsed_s > 0
            else 0.0
        )
        previous_humidity_pct = humidity
        if config.profile == "solar_utility":
            irradiance = max(0.0, 1000.0 * math.sin(day_phase))
            load_fraction = irradiance / 1000
            ev_active: bool | None = None
            ev_power: float | None = None
            dc_voltage = 1000.0
        else:
            cycle_s = max(60.0, min(600.0, config.duration_s / 3))
            session_phase = elapsed_s % cycle_s
            session_active = _nb_session_active(config, elapsed_s)
            ramp_duration_s = min(10.0, cycle_s * 0.2)
            if not session_active:
                load_fraction = 0.0
            elif session_phase < ramp_duration_s:
                load_fraction = session_phase / ramp_duration_s
            else:
                load_fraction = 0.8
            ev_active = session_active
            ev_power = round(config.nominal_power_kw * load_fraction, 6)
            irradiance = None
            dc_voltage = 800.0

        load_fraction = max(0.0, min(1.0, load_fraction))
        target_heatsink = ambient + 8 + 34 * load_fraction
        alpha = 1 - math.exp(-physical_step_s / config.thermal_time_constant_s)
        for _ in range(integration_steps):
            heatsink_temp += alpha * (target_heatsink - heatsink_temp)

        if config.degradation_mode == DegradationMode.IGBT_THERMAL_FATIGUE:
            thermal_damage_rise = config.temperature_rise_at_full_load_c * damage
        else:
            thermal_damage_rise = 0.0
        target_junction = (
            heatsink_temp
            + config.temperature_rise_at_full_load_c * load_fraction
            + thermal_damage_rise * load_fraction
        )
        if previous_timestamp is None:
            junction_temp = target_junction
        else:
            for _ in range(integration_steps):
                junction_temp += alpha * (target_junction - junction_temp)
        previous_timestamp = timestamp

        esr_ratio = (
            1 + damage**config.esr_growth_exponent
            if config.degradation_mode == DegradationMode.DC_LINK_CAPACITOR
            else 1.0
        )
        insulation_factor = (
            max(0.1, 1 - 0.9 * damage * humidity_exposure_factor)
            if config.degradation_mode == DegradationMode.INSULATION
            else 1.0
        )
        internal_esr = config.esr_baseline_mohm * esr_ratio
        internal_insulation = (
            config.insulation_baseline_megaohm
            * insulation_factor
            * (1 - 0.35 * humidity / 100)
        )
        dc_power_kw = config.nominal_power_kw * load_fraction
        dc_current = dc_power_kw * 1000 / dc_voltage
        phase_current = dc_power_kw * 1000 / (math.sqrt(3) * 400)
        phase_offset = rng.gauss(0, 0.0015)
        if config.degradation_mode == DegradationMode.PHASE_IMBALANCE:
            phase_offset += config.phase_imbalance_at_full_damage_pct / 100 * damage
        current_l1 = _noisy(rng, phase_current * (1 + phase_offset), config.sensor_noise_stddev)
        current_l2 = _noisy(rng, phase_current, config.sensor_noise_stddev)
        current_l3 = _noisy(rng, phase_current * (1 - phase_offset), config.sensor_noise_stddev)
        mean_current = (current_l1 + current_l2 + current_l3) / 3
        imbalance = (
            max(
                abs(current_l1 - mean_current),
                abs(current_l2 - mean_current),
                abs(current_l3 - mean_current),
            )
            / mean_current
            * 100
            if mean_current
            else 0.0
        )

        observable = {
            "env_temp_c": _noisy(rng, ambient, config.sensor_noise_stddev),
            "relative_humidity_pct": round(humidity, 6),
            "irradiance_w_m2": (
                _noisy(rng, irradiance, config.sensor_noise_stddev)
                if irradiance is not None
                else None
            ),
            "ev_session_active": ev_active,
            "ev_power_kw": (
                _noisy(rng, ev_power, config.sensor_noise_stddev)
                if ev_power is not None
                else None
            ),
            "heatsink_temp_c": _noisy(
                rng, heatsink_temp, config.sensor_noise_stddev
            ),
            "dc_bus_voltage_v": _noisy(rng, dc_voltage, config.sensor_noise_stddev),
            "dc_bus_current_a": _noisy(
                rng, dc_current, config.sensor_noise_stddev
            ),
            "ac_current_l1_a": current_l1,
            "ac_current_l2_a": current_l2,
            "ac_current_l3_a": current_l3,
            "dc_link_esr_est_mohm": _noisy(
                rng, internal_esr, config.sensor_noise_stddev * 0.01
            ),
            "insulation_resistance_est_megaohm": _noisy(
                rng, internal_insulation, config.sensor_noise_stddev * 0.01
            ),
            "thdi_pct": round(max(0.0, _noisy(rng, 1.5 + load_fraction, 0.1)), 6),
            "thermal_derating_active": False,
        }
        missing_fields: list[str] = []
        if sample_index % 97 == 53:
            field_to_drop = (
                "irradiance_w_m2"
                if config.profile == "solar_utility"
                else "ev_power_kw"
            )
            observable[field_to_drop] = None
            missing_fields.append(f"observables.{field_to_drop}")

        timestamp_text = timestamp.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
        next_expected_interval_ms = config.sampling_period_ms
        if (
            config.profile == "ev_nb"
            and config.nb_idle_sampling_period_ms is not None
            and ev_active is False
        ):
            next_expected_interval_ms = config.nb_idle_sampling_period_ms
        telemetry.append(
            {
                "schema_version": "1.0.0",
                "run_id": config.run_id,
                "sample_index": sample_index,
                "timestamp": timestamp_text,
                "next_expected_interval_ms": next_expected_interval_ms,
                "asset_id": config.asset_id,
                "profile": config.profile,
                "observables": observable,
                "features": {"ac_current_imbalance_pct": round(imbalance, 6)},
                "quality": {"missing_fields": missing_fields},
            }
        )

        if (
            failure_time is None
            and config.degradation_mode != DegradationMode.NONE
            and (
                damage >= 1
                or (
                    config.degradation_mode == DegradationMode.IGBT_THERMAL_FATIGUE
                    and junction_temp >= max_failure_temperature
                )
                or (
                    config.degradation_mode == DegradationMode.DC_LINK_CAPACITOR
                    and esr_ratio >= config.esr_failure_ratio
                )
                or (
                    config.degradation_mode == DegradationMode.INSULATION
                    and internal_insulation
                    <= config.insulation_failure_megaohm
                )
                or (
                    config.degradation_mode == DegradationMode.PHASE_IMBALANCE
                    and imbalance >= config.phase_imbalance_failure_threshold_pct
                )
            )
        ):
            failure_time = timestamp

        if damage >= config.milestones.end_of_life_damage_fraction:
            degradation_state = "critical"
        elif damage >= config.milestones.predictive_warning_damage_fraction:
            degradation_state = "early_warning"
        else:
            degradation_state = "healthy"
        labels.append(
            {
                "run_id": config.run_id,
                "asset_id": config.asset_id,
                "timestamp": timestamp_text,
                "ground_truth": {
                    "junction_temp_c": round(junction_temp, 6),
                    "dc_link_esr_mohm": round(internal_esr, 6),
                    "insulation_resistance_megaohm": round(
                        internal_insulation, 6
                    ),
                    "damage_fraction": round(damage, 6),
                    "humidity_exposure_factor": round(
                        humidity_exposure_factor, 6
                    ),
                    "degradation_mode": config.degradation_mode.value,
                    "degradation_state": degradation_state,
                    "event_onset_utc": (
                        _timestamp_text(event_onset)
                    ),
                    "predictive_warning_target_utc": _timestamp_text(warning_time),
                    "synthetic_protection_event_utc": _timestamp_text(
                        protection_time
                    ),
                    "end_of_life_event_utc": _timestamp_text(end_of_life_time),
                    "predictive_warning_target_active": (
                        warning_time is not None and timestamp >= warning_time
                    ),
                    "synthetic_protection_active": (
                        protection_time is not None and timestamp >= protection_time
                    ),
                    "end_of_life_reached": (
                        end_of_life_time is not None and timestamp >= end_of_life_time
                    ),
                    "failure_time_utc": (
                        _timestamp_text(failure_time)
                    ),
                    "failure_within_horizon": False,
                },
            }
        )

    failure_time_text = (
        _timestamp_text(failure_time)
    )
    for label in labels:
        timestamp = datetime.fromisoformat(label["timestamp"].replace("Z", "+00:00"))
        label["ground_truth"]["failure_time_utc"] = failure_time_text
        label["ground_truth"]["failure_within_horizon"] = (
            failure_time is not None
            and timestamp <= failure_time
            <= timestamp + timedelta(seconds=config.prediction_horizon_s)
        )

    return SimulatedRun(
        config=config,
        telemetry=tuple(telemetry),
        labels=tuple(labels),
        event_onset_utc=event_onset,
        failure_time_utc=failure_time,
    )


def generate_dataset(
    runs: Sequence[SyntheticRunConfig],
    *,
    train_fraction: float,
    validation_fraction: float,
) -> SyntheticDataset:
    """Partition whole runs first, then generate isolated telemetry and labels."""
    if not runs:
        raise ValueError("at least one run configuration is required")
    partitions = assign_run_partitions(
        [
            RunDescriptor(run.run_id, run.started_at)
            for run in runs
        ],
        train_fraction=train_fraction,
        validation_fraction=validation_fraction,
    )
    simulated_runs = [simulate_run(run) for run in runs]
    telemetry = tuple(
        row for run in simulated_runs for row in run.telemetry
    )
    labels = tuple(row for run in simulated_runs for row in run.labels)
    manifest = {
        "schema_version": "1.0.0",
        "partition_fractions": {
            "train": train_fraction,
            "validation": validation_fraction,
            "test": 1 - train_fraction - validation_fraction,
        },
        "runs": [
            {
                "run_id": run.config.run_id,
                "seed": run.config.seed,
                "profile": run.config.profile,
                "scenario": run.config.degradation_mode.value,
                "schema_version": "1.0.0",
                "sampling_period_ms": run.config.sampling_period_ms,
                "telemetry_schedule": {
                    "mode": (
                        "nb_session_idle"
                        if run.config.nb_idle_sampling_period_ms is not None
                        else "fixed"
                    ),
                    "session_interval_ms": run.config.sampling_period_ms,
                    "idle_interval_ms": (
                        run.config.nb_idle_sampling_period_ms
                        if run.config.nb_idle_sampling_period_ms is not None
                        else run.config.sampling_period_ms
                    ),
                    "provenance": "synthetic_assumption",
                },
                "physical_step_ms": run.config.physical_step_ms,
                "prediction_horizon_s": run.config.prediction_horizon_s,
                "duration_s": run.config.duration_s,
                "eval_group": partitions[run.config.run_id].value,
                "config": {
                    "parameter_provenance": {
                        "physical_step_ms": _synthetic_parameter(
                            run.config.physical_step_ms,
                            "ms",
                            "internal physical integration step",
                        ),
                        "sampling_period_ms": _synthetic_parameter(
                            run.config.sampling_period_ms,
                            "ms",
                            "telemetry interval during session or fixed mode",
                        ),
                        "nb_idle_sampling_period_ms": _synthetic_parameter(
                            run.config.nb_idle_sampling_period_ms,
                            "ms",
                            "telemetry interval during NB idle mode, when configured",
                        ),
                        "prediction_horizon_s": _synthetic_parameter(
                            run.config.prediction_horizon_s,
                            "s",
                            "failure prediction target horizon",
                        ),
                        "degradation_onset_fraction": _synthetic_parameter(
                            run.config.degradation_onset_fraction,
                            "fraction_of_run",
                            "start of the synthetic degradation trajectory",
                        ),
                        "ambient_temperature_c": _synthetic_parameter(
                            run.config.ambient_temperature_c,
                            "degC",
                            "ambient temperature baseline",
                        ),
                        "sensor_noise_stddev": _synthetic_parameter(
                            run.config.sensor_noise_stddev,
                            "signal_specific_units",
                            "synthetic sensor noise scale",
                        ),
                        "nominal_power_kw": _synthetic_parameter(
                            run.config.nominal_power_kw,
                            "kW",
                            "nominal asset power used for load normalization",
                        ),
                        "thermal_time_constant_s": _synthetic_parameter(
                            run.config.thermal_time_constant_s,
                            "s",
                            "synthetic thermal response time constant",
                        ),
                        "temperature_rise_at_full_load_c": _synthetic_parameter(
                            run.config.temperature_rise_at_full_load_c,
                            "degC",
                            "synthetic temperature rise at full load",
                        ),
                        "insulation_baseline_megaohm": _synthetic_parameter(
                            run.config.insulation_baseline_megaohm,
                            "Mohm",
                            "synthetic insulation baseline",
                        ),
                        "esr_baseline_mohm": _synthetic_parameter(
                            run.config.esr_baseline_mohm,
                            "mohm",
                            "synthetic capacitor ESR baseline",
                        ),
                        "thermal_failure_threshold_c": _synthetic_parameter(
                            run.config.thermal_failure_threshold_c,
                            "degC",
                            "synthetic IGBT failure criterion, not a protection limit",
                        ),
                        "esr_failure_ratio": _synthetic_parameter(
                            run.config.esr_failure_ratio,
                            "ratio",
                            "synthetic capacitor failure criterion",
                        ),
                        "insulation_failure_megaohm": _synthetic_parameter(
                            run.config.insulation_failure_megaohm,
                            "Mohm",
                            "synthetic insulation failure criterion",
                        ),
                        "esr_growth_exponent": _synthetic_parameter(
                            run.config.esr_growth_exponent,
                            "dimensionless",
                            "power-law exponent for synthetic ESR growth",
                        ),
                        "humidity_baseline_pct": _synthetic_parameter(
                            run.config.humidity_baseline_pct,
                            "%",
                            "relative humidity baseline for the scenario",
                        ),
                        "humidity_daily_amplitude_pct": _synthetic_parameter(
                            run.config.humidity_daily_amplitude_pct,
                            "%",
                            "relative humidity sinusoidal amplitude",
                        ),
                        "humidity_reference_pct": _synthetic_parameter(
                            run.config.humidity_reference_pct,
                            "%",
                            "reference humidity for normalized accumulated exposure",
                        ),
                        "phase_imbalance_at_full_damage_pct": _synthetic_parameter(
                            run.config.phase_imbalance_at_full_damage_pct,
                            "%",
                            "phase imbalance target at full synthetic damage",
                        ),
                        "phase_imbalance_failure_threshold_pct": _synthetic_parameter(
                            run.config.phase_imbalance_failure_threshold_pct,
                            "%",
                            "synthetic phase imbalance failure criterion",
                        ),
                    },
                    "degradation_onset_fraction": run.config.degradation_onset_fraction,
                    "ambient_temperature_c": run.config.ambient_temperature_c,
                    "sensor_noise_stddev": run.config.sensor_noise_stddev,
                    "physical_step_ms": run.config.physical_step_ms,
                    "sampling_period_ms": run.config.sampling_period_ms,
                    "nb_idle_sampling_period_ms": (
                        run.config.nb_idle_sampling_period_ms
                    ),
                    "nominal_power_kw": run.config.nominal_power_kw,
                    "thermal_time_constant_s": run.config.thermal_time_constant_s,
                    "temperature_rise_at_full_load_c": (
                        run.config.temperature_rise_at_full_load_c
                    ),
                    "insulation_baseline_megaohm": (
                        run.config.insulation_baseline_megaohm
                    ),
                    "esr_baseline_mohm": run.config.esr_baseline_mohm,
                    "thermal_failure_threshold_c": (
                        run.config.thermal_failure_threshold_c
                    ),
                    "esr_failure_ratio": run.config.esr_failure_ratio,
                    "insulation_failure_megaohm": (
                        run.config.insulation_failure_megaohm
                    ),
                    "event_milestones": {
                        "predictive_warning": {
                            "damage_fraction": (
                                run.config.milestones.predictive_warning_damage_fraction
                            ),
                            "unit": "normalized_synthetic_damage_fraction",
                            "source": "synthetic scenario assumption",
                            "confidence": "low",
                            "status": "synthetic_unvalidated",
                        },
                        "synthetic_protection": {
                            "damage_fraction": (
                                run.config.milestones.synthetic_protection_damage_fraction
                            ),
                            "unit": "normalized_synthetic_damage_fraction",
                            "source": "synthetic scenario assumption",
                            "confidence": "low",
                            "status": "synthetic_unvalidated",
                        },
                        "end_of_life": {
                            "damage_fraction": (
                                run.config.milestones.end_of_life_damage_fraction
                            ),
                            "unit": "normalized_synthetic_damage_fraction",
                            "source": "synthetic scenario assumption",
                            "confidence": "low",
                            "status": "synthetic_unvalidated",
                        },
                    },
                    "parameter_status": "synthetic_unvalidated",
                },
            }
            for run in simulated_runs
        ],
    }
    return SyntheticDataset(telemetry, labels, manifest)


def write_dataset(dataset: SyntheticDataset, output_dir: str | Path) -> None:
    """Write strict JSONL telemetry/labels and a separate run manifest."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output / "telemetry.jsonl", dataset.telemetry)
    _write_jsonl(output / "labels.jsonl", dataset.labels)
    _write_json(output / "manifest.json", dataset.manifest)


def _write_jsonl(path: Path, rows: Sequence[dict[str, object]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(
                    json.dumps(
                        row, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                    )
                    + "\n"
                )
        temporary.replace(path)
    except OSError:
        if temporary.exists():
            temporary.unlink()
        raise


def _write_json(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    except OSError:
        if temporary.exists():
            temporary.unlink()
        raise
