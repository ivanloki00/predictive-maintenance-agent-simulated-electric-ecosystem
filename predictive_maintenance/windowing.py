"""Configuration-driven regime classification and causal time-window selection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import math
from types import MappingProxyType
from typing import Mapping


class Regime(str, Enum):
    SOLAR_ACTIVE = "solar_active"
    SOLAR_LOW = "solar_low"
    IDLE = "idle"
    CHARGING_STEADY = "charging_steady"
    CHARGING_RAMP = "charging_ramp"
    UNKNOWN = "unknown"


class DatasetPartition(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class WindowStatus(str, Enum):
    READY = "ready"
    INSUFFICIENT_HISTORY = "insufficient_history"
    NOT_DUE = "not_due"


_KNOWN_WINDOW_REGIMES = frozenset(
    {
        Regime.SOLAR_ACTIVE,
        Regime.SOLAR_LOW,
        Regime.IDLE,
        Regime.CHARGING_STEADY,
        Regime.CHARGING_RAMP,
    }
)
_OBSERVABLE_FIELDS = frozenset(
    {
        "env_temp_c",
        "relative_humidity_pct",
        "irradiance_w_m2",
        "ev_session_active",
        "ev_power_kw",
        "heatsink_temp_c",
        "dc_bus_voltage_v",
        "dc_bus_current_a",
        "ac_current_l1_a",
        "ac_current_l2_a",
        "ac_current_l3_a",
        "dc_link_esr_est_mohm",
        "insulation_resistance_est_megaohm",
        "thdi_pct",
        "thermal_derating_active",
    }
)
_FEATURE_FIELDS = frozenset({"ac_current_imbalance_pct"})


def _validate_finite_nonnegative(name: str, value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be finite and non-negative")


def _validate_timestamp(timestamp: datetime) -> None:
    if (
        not isinstance(timestamp, datetime)
        or timestamp.tzinfo is None
        or timestamp.utcoffset() != timedelta(0)
    ):
        raise ValueError("timestamps must be timezone-aware UTC datetimes")


def window_sample_count(duration_s: float, sampling_period_s: float) -> int:
    """Return the sample count for duration D, including both window endpoints."""
    _validate_finite_nonnegative("duration_s", duration_s)
    if duration_s == 0:
        raise ValueError("duration_s must be greater than zero")
    if (
        isinstance(sampling_period_s, bool)
        or not isinstance(sampling_period_s, (int, float))
        or not math.isfinite(sampling_period_s)
        or sampling_period_s <= 0
    ):
        raise ValueError("sampling_period_s must be finite and greater than zero")
    return math.ceil(duration_s / sampling_period_s) + 1


@dataclass(frozen=True)
class SolarRegimeConfig:
    irradiance_on_w_m2: float
    irradiance_off_w_m2: float
    debounce_s: float

    def __post_init__(self) -> None:
        _validate_finite_nonnegative("irradiance_on_w_m2", self.irradiance_on_w_m2)
        _validate_finite_nonnegative(
            "irradiance_off_w_m2", self.irradiance_off_w_m2
        )
        _validate_finite_nonnegative("debounce_s", self.debounce_s)
        if self.irradiance_on_w_m2 <= self.irradiance_off_w_m2:
            raise ValueError("solar on threshold must be greater than off threshold")


@dataclass(frozen=True)
class NBRegimeConfig:
    ramp_threshold_kw_per_s: float
    debounce_s: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.ramp_threshold_kw_per_s, bool)
            or not isinstance(self.ramp_threshold_kw_per_s, (int, float))
            or not math.isfinite(self.ramp_threshold_kw_per_s)
            or self.ramp_threshold_kw_per_s <= 0
        ):
            raise ValueError("ramp_threshold_kw_per_s must be finite and greater than zero")
        _validate_finite_nonnegative("debounce_s", self.debounce_s)


@dataclass(frozen=True)
class WindowingConfig:
    sampling_period_ms: int
    max_gap_s: float
    max_history_s: float
    stride_s: float
    max_samples: int
    durations_s: Mapping[Regime, float]
    minimum_samples: Mapping[Regime, int] | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.sampling_period_ms, bool)
            or not isinstance(self.sampling_period_ms, int)
            or self.sampling_period_ms <= 0
        ):
            raise ValueError("sampling_period_ms must be a positive integer")
        if (
            isinstance(self.max_samples, bool)
            or not isinstance(self.max_samples, int)
            or self.max_samples <= 0
        ):
            raise ValueError("max_samples must be a positive integer")
        _validate_finite_nonnegative("max_gap_s", self.max_gap_s)
        _validate_finite_nonnegative("max_history_s", self.max_history_s)
        _validate_finite_nonnegative("stride_s", self.stride_s)
        if self.max_gap_s == 0 or self.max_history_s == 0:
            raise ValueError("max_gap_s and max_history_s must be greater than zero")
        if self.stride_s == 0:
            raise ValueError("stride_s must be greater than zero")
        durations = dict(self.durations_s)
        if set(durations) != _KNOWN_WINDOW_REGIMES:
            raise ValueError("durations_s must define every predictable regime exactly once")
        for regime, duration_s in durations.items():
            if not isinstance(regime, Regime):
                raise ValueError("durations_s keys must be Regime values")
            _validate_finite_nonnegative(f"{regime.value} duration", duration_s)
            if duration_s == 0:
                raise ValueError(f"{regime.value} duration must be greater than zero")
            if duration_s > self.max_history_s:
                raise ValueError(f"{regime.value} duration exceeds max_history_s")

        fixed_cadence = self.minimum_samples is None
        if fixed_cadence:
            minimum_samples = {
                regime: window_sample_count(
                    duration_s, self.sampling_period_ms / 1000
                )
                for regime, duration_s in durations.items()
            }
        else:
            minimum_samples = dict(self.minimum_samples)
            if set(minimum_samples) != _KNOWN_WINDOW_REGIMES:
                raise ValueError(
                    "minimum_samples must define every predictable regime exactly once"
                )
            for regime, sample_count in minimum_samples.items():
                if (
                    not isinstance(regime, Regime)
                    or isinstance(sample_count, bool)
                    or not isinstance(sample_count, int)
                    or sample_count <= 0
                ):
                    raise ValueError(
                        "minimum_samples values must be positive integers keyed by Regime"
                    )

        capacity_required = max(minimum_samples.values())
        if fixed_cadence:
            capacity_required = max(
                capacity_required,
                window_sample_count(
                    self.max_history_s, self.sampling_period_ms / 1000
                ),
            )
        if self.max_samples < capacity_required:
            raise ValueError(
                "max_samples must hold the configured history and regime minimums"
            )
        object.__setattr__(self, "durations_s", MappingProxyType(durations))
        object.__setattr__(
            self, "minimum_samples", MappingProxyType(minimum_samples)
        )

    def duration_for(self, regime: Regime) -> float:
        if regime not in self.durations_s:
            raise ValueError(f"no prediction window is configured for {regime.value}")
        return self.durations_s[regime]

    def minimum_samples_for(self, regime: Regime) -> int:
        if regime not in self.minimum_samples:
            raise ValueError(f"no minimum sample count is configured for {regime.value}")
        return self.minimum_samples[regime]


class SolarRegimeClassifier:
    """Classify solar activity with hysteresis and time-based debounce."""

    def __init__(self, config: SolarRegimeConfig) -> None:
        self._config = config
        self._regime = Regime.UNKNOWN
        self._candidate: Regime | None = None
        self._candidate_since: datetime | None = None
        self._last_timestamp: datetime | None = None

    def reset(self) -> None:
        self._regime = Regime.UNKNOWN
        self._candidate = None
        self._candidate_since = None
        self._last_timestamp = None

    def update(
        self, timestamp: datetime, irradiance_w_m2: float | None
    ) -> Regime:
        _validate_timestamp(timestamp)
        self._validate_order(timestamp)
        self._last_timestamp = timestamp
        if (
            irradiance_w_m2 is None
            or isinstance(irradiance_w_m2, bool)
            or not isinstance(irradiance_w_m2, (int, float))
            or not math.isfinite(irradiance_w_m2)
            or irradiance_w_m2 < 0
        ):
            self._clear_candidate()
            return Regime.UNKNOWN

        target: Regime | None = None
        if self._regime == Regime.SOLAR_ACTIVE:
            if irradiance_w_m2 <= self._config.irradiance_off_w_m2:
                target = Regime.SOLAR_LOW
        elif self._regime == Regime.SOLAR_LOW:
            if irradiance_w_m2 >= self._config.irradiance_on_w_m2:
                target = Regime.SOLAR_ACTIVE
        elif irradiance_w_m2 >= self._config.irradiance_on_w_m2:
            target = Regime.SOLAR_ACTIVE
        elif irradiance_w_m2 <= self._config.irradiance_off_w_m2:
            target = Regime.SOLAR_LOW

        return self._confirm_after_debounce(target, timestamp)

    def _confirm_after_debounce(
        self, target: Regime | None, timestamp: datetime
    ) -> Regime:
        if target is None:
            self._clear_candidate()
            return self._regime
        if target != self._candidate:
            self._candidate = target
            self._candidate_since = timestamp
        if (
            self._candidate_since is not None
            and (timestamp - self._candidate_since).total_seconds()
            >= self._config.debounce_s
        ):
            self._regime = target
            self._clear_candidate()
        return self._regime

    def _validate_order(self, timestamp: datetime) -> None:
        if self._last_timestamp is not None and timestamp <= self._last_timestamp:
            raise ValueError("timestamps must be strictly increasing")

    def _clear_candidate(self) -> None:
        self._candidate = None
        self._candidate_since = None


class NBRegimeClassifier:
    """Classify charger operation; recognize clear power ramps immediately."""

    def __init__(self, config: NBRegimeConfig) -> None:
        self._config = config
        self._regime = Regime.UNKNOWN
        self._candidate: Regime | None = None
        self._candidate_since: datetime | None = None
        self._last_timestamp: datetime | None = None
        self._previous_power_kw: float | None = None
        self._previous_power_timestamp: datetime | None = None

    def reset(self) -> None:
        self._regime = Regime.UNKNOWN
        self._candidate = None
        self._candidate_since = None
        self._last_timestamp = None
        self._previous_power_kw = None
        self._previous_power_timestamp = None

    def update(
        self,
        timestamp: datetime,
        ev_session_active: bool | None,
        ev_power_kw: float | None,
    ) -> Regime:
        _validate_timestamp(timestamp)
        self._validate_order(timestamp)
        self._last_timestamp = timestamp
        if (
            ev_session_active is None
            or not isinstance(ev_session_active, bool)
            or ev_power_kw is None
            or isinstance(ev_power_kw, bool)
            or not isinstance(ev_power_kw, (int, float))
            or not math.isfinite(ev_power_kw)
            or ev_power_kw < 0
        ):
            self._clear_candidate()
            self._previous_power_kw = None
            self._previous_power_timestamp = None
            return Regime.UNKNOWN

        previous_power = self._previous_power_kw
        previous_power_timestamp = self._previous_power_timestamp
        self._previous_power_kw = ev_power_kw
        self._previous_power_timestamp = timestamp
        if not ev_session_active:
            return self._confirm_after_debounce(Regime.IDLE, timestamp)

        ramp_detected = False
        if previous_power is not None and previous_power_timestamp is not None:
            elapsed_s = (timestamp - previous_power_timestamp).total_seconds()
            ramp_rate = abs(ev_power_kw - previous_power) / elapsed_s
            ramp_detected = ramp_rate >= self._config.ramp_threshold_kw_per_s
        if ramp_detected:
            self._regime = Regime.CHARGING_RAMP
            self._clear_candidate()
            return self._regime

        if self._regime in {Regime.UNKNOWN, Regime.IDLE}:
            self._regime = Regime.CHARGING_STEADY
            self._clear_candidate()
            return self._regime
        return self._confirm_after_debounce(Regime.CHARGING_STEADY, timestamp)

    def _validate_order(self, timestamp: datetime) -> None:
        if self._last_timestamp is not None and timestamp <= self._last_timestamp:
            raise ValueError("timestamps must be strictly increasing")

    def _clear_candidate(self) -> None:
        self._candidate = None
        self._candidate_since = None

    def _confirm_after_debounce(self, target: Regime, timestamp: datetime) -> Regime:
        if target == self._regime:
            self._clear_candidate()
            return self._regime
        if target != self._candidate:
            self._candidate = target
            self._candidate_since = timestamp
        if (
            self._candidate_since is not None
            and (timestamp - self._candidate_since).total_seconds()
            >= self._config.debounce_s
        ):
            self._regime = target
            self._clear_candidate()
        return self._regime


@dataclass(frozen=True)
class WindowSample:
    """An inference-safe sample containing only allowlisted telemetry fields."""

    schema_version: str
    run_id: str
    sample_index: int
    timestamp: datetime
    asset_id: str
    profile: str
    observables: Mapping[str, object]
    features: Mapping[str, object]
    next_expected_interval_s: float | None = None

    def __post_init__(self) -> None:
        _validate_timestamp(self.timestamp)
        if not self.schema_version or not self.run_id or not self.asset_id:
            raise ValueError("schema_version, run_id, and asset_id are required")
        if (
            isinstance(self.sample_index, bool)
            or not isinstance(self.sample_index, int)
            or self.sample_index < 0
        ):
            raise ValueError("sample_index must be a non-negative integer")
        if self.profile not in {"solar_utility", "ev_nb"}:
            raise ValueError("profile must be solar_utility or ev_nb")
        if self.next_expected_interval_s is not None and (
            isinstance(self.next_expected_interval_s, bool)
            or not isinstance(self.next_expected_interval_s, (int, float))
            or not math.isfinite(self.next_expected_interval_s)
            or self.next_expected_interval_s <= 0
        ):
            raise ValueError(
                "next_expected_interval_s must be finite and greater than zero"
            )
        observables = dict(self.observables)
        features = dict(self.features)
        unexpected_observables = set(observables) - _OBSERVABLE_FIELDS
        unexpected_features = set(features) - _FEATURE_FIELDS
        if unexpected_observables:
            raise ValueError(
                f"unsupported observable fields: {sorted(unexpected_observables)}"
            )
        if unexpected_features:
            raise ValueError(f"unsupported feature fields: {sorted(unexpected_features)}")
        for field, value in observables.items():
            if field in {"ev_session_active", "thermal_derating_active"}:
                if value is not None and not isinstance(value, bool):
                    raise ValueError(f"{field} must be a boolean or None")
            elif value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{field} must be a finite number or None")
        for field, value in features.items():
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{field} must be a finite number or None")
        object.__setattr__(self, "observables", MappingProxyType(observables))
        object.__setattr__(self, "features", MappingProxyType(features))


@dataclass(frozen=True)
class WindowSelection:
    status: WindowStatus
    samples: tuple[WindowSample, ...]
    requested_duration_s: float
    effective_duration_s: float
    expected_sample_count: int


class TemporalWindowBuffer:
    """Bounded, causal buffer that never mixes runs, assets, schemas, or splits."""

    def __init__(self, config: WindowingConfig) -> None:
        self._config = config
        self._samples: deque[WindowSample] = deque(maxlen=config.max_samples)
        self._partition: DatasetPartition | None = None
        self._identity: tuple[str, str, str, str] | None = None
        self._last_selection_at: datetime | None = None

    def reset(self) -> None:
        self._samples.clear()
        self._partition = None
        self._identity = None
        self._last_selection_at = None

    def append(
        self, sample: WindowSample, partition: DatasetPartition
    ) -> None:
        if not isinstance(partition, DatasetPartition):
            raise ValueError("partition must be a DatasetPartition")
        identity = (
            sample.run_id,
            sample.asset_id,
            sample.schema_version,
            sample.profile,
        )
        if self._identity is not None and (
            identity != self._identity or partition != self._partition
        ):
            self.reset()

        if self._samples:
            previous = self._samples[-1]
            elapsed_s = (sample.timestamp - previous.timestamp).total_seconds()
            if elapsed_s <= 0:
                raise ValueError("sample timestamps must be strictly increasing")
            if sample.sample_index <= previous.sample_index:
                raise ValueError("sample_index must be strictly increasing")
            expected_interval_s = (
                previous.next_expected_interval_s
                if previous.next_expected_interval_s is not None
                else self._config.sampling_period_ms / 1000
            )
            if elapsed_s > max(expected_interval_s, self._config.max_gap_s):
                self._samples.clear()
                self._last_selection_at = None

        self._identity = identity
        self._partition = partition
        self._samples.append(sample)

    def select(
        self,
        duration_s: float,
        *,
        minimum_samples: int | None = None,
        force: bool = False,
    ) -> WindowSelection:
        if minimum_samples is None:
            expected_count = window_sample_count(
                duration_s, self._config.sampling_period_ms / 1000
            )
        elif (
            isinstance(minimum_samples, bool)
            or not isinstance(minimum_samples, int)
            or minimum_samples <= 0
        ):
            raise ValueError("minimum_samples must be a positive integer")
        else:
            expected_count = minimum_samples
        if duration_s > self._config.max_history_s:
            raise ValueError("duration_s exceeds configured max_history_s")
        if not self._samples:
            return WindowSelection(
                WindowStatus.INSUFFICIENT_HISTORY, (), duration_s, 0.0, expected_count
            )

        latest = self._samples[-1].timestamp
        if (
            not force
            and self._last_selection_at is not None
            and (latest - self._last_selection_at).total_seconds()
            < self._config.stride_s
        ):
            return WindowSelection(
                WindowStatus.NOT_DUE, (), duration_s, 0.0, expected_count
            )

        samples = tuple(self._samples)
        start_index = len(samples) - 1
        while start_index > 0:
            covered_duration = (latest - samples[start_index].timestamp).total_seconds()
            if covered_duration >= duration_s:
                break
            start_index -= 1
        selected = samples[start_index:]
        covered_duration = (
            (selected[-1].timestamp - selected[0].timestamp).total_seconds()
            if selected
            else 0.0
        )
        self._last_selection_at = latest
        enough_history = (
            selected
            and len(selected) >= expected_count
            and covered_duration >= duration_s
        )
        status = (
            WindowStatus.READY
            if enough_history
            else WindowStatus.INSUFFICIENT_HISTORY
        )
        return WindowSelection(
            status, selected, duration_s, covered_duration, expected_count
        )
