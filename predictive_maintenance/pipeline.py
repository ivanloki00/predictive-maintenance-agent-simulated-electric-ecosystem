"""Apply run-level partitions, regime classification, and adaptive windows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from typing import Mapping, Sequence

from .simulator import SyntheticDataset
from .windowing import (
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
)


def _synthetic_parameter(value: object, unit: str, meaning: str) -> dict[str, object]:
    return {
        "value": value,
        "unit": unit,
        "meaning": meaning,
        "source": "synthetic processing configuration",
        "confidence": "low",
        "status": "synthetic_unvalidated",
    }


@dataclass(frozen=True)
class WindowProcessingConfig:
    solar: SolarRegimeConfig
    nb: NBRegimeConfig
    windows: WindowingConfig

    def as_manifest(self) -> dict[str, object]:
        if self.windows.minimum_samples is None:
            raise RuntimeError("window minimum sample counts were not initialized")
        return {
            "sampling_period_ms": self.windows.sampling_period_ms,
            "max_gap_s": self.windows.max_gap_s,
            "max_history_s": self.windows.max_history_s,
            "stride_s": self.windows.stride_s,
            "max_samples": self.windows.max_samples,
            "minimum_samples": {
                regime.value: sample_count
                for regime, sample_count in self.windows.minimum_samples.items()
            },
            "durations_s": {
                regime.value: duration
                for regime, duration in self.windows.durations_s.items()
            },
            "solar": asdict(self.solar),
            "nb": asdict(self.nb),
            "parameter_status": "synthetic_unvalidated",
            "parameter_provenance": {
                "sampling_period_ms": _synthetic_parameter(
                    self.windows.sampling_period_ms,
                    "ms",
                    "fixed-cadence fallback and minimum-sample derivation",
                ),
                "max_gap_s": _synthetic_parameter(
                    self.windows.max_gap_s,
                    "s",
                    "minimum allowed gap before history reset",
                ),
                "max_history_s": _synthetic_parameter(
                    self.windows.max_history_s,
                    "s",
                    "upper bound on selectable history duration",
                ),
                "stride_s": _synthetic_parameter(
                    self.windows.stride_s,
                    "s",
                    "minimum interval between ordinary window emissions",
                ),
                "max_samples": _synthetic_parameter(
                    self.windows.max_samples,
                    "samples",
                    "maximum retained samples per causal buffer",
                ),
                "durations_s": {
                    regime.value: _synthetic_parameter(
                        duration,
                        "s",
                        f"causal window duration for {regime.value}",
                    )
                    for regime, duration in self.windows.durations_s.items()
                },
                "minimum_samples": {
                    regime.value: _synthetic_parameter(
                        sample_count,
                        "samples",
                        f"minimum observations for {regime.value}",
                    )
                    for regime, sample_count in self.windows.minimum_samples.items()
                },
                "solar": {
                    "irradiance_on_w_m2": _synthetic_parameter(
                        self.solar.irradiance_on_w_m2,
                        "W/m2",
                        "solar-active hysteresis threshold",
                    ),
                    "irradiance_off_w_m2": _synthetic_parameter(
                        self.solar.irradiance_off_w_m2,
                        "W/m2",
                        "solar-low hysteresis threshold",
                    ),
                    "debounce_s": _synthetic_parameter(
                        self.solar.debounce_s,
                        "s",
                        "minimum solar regime transition persistence",
                    ),
                },
                "nb": {
                    "ramp_threshold_kw_per_s": _synthetic_parameter(
                        self.nb.ramp_threshold_kw_per_s,
                        "kW/s",
                        "charging ramp classification threshold",
                    ),
                    "debounce_s": _synthetic_parameter(
                        self.nb.debounce_s,
                        "s",
                        "minimum NB regime transition persistence",
                    ),
                },
            },
        }


@dataclass(frozen=True)
class WindowFrame:
    run_id: str
    asset_id: str
    timestamp: str
    regime: Regime
    status: WindowStatus
    requested_duration_s: float
    effective_duration_s: float
    expected_sample_count: int
    sample_indices: tuple[int, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "asset_id": self.asset_id,
            "timestamp": self.timestamp,
            "regime": self.regime.value,
            "status": self.status.value,
            "requested_duration_s": self.requested_duration_s,
            "effective_duration_s": self.effective_duration_s,
            "expected_sample_count": self.expected_sample_count,
            "sample_indices": list(self.sample_indices),
        }


def _parse_utc(timestamp: object) -> datetime:
    if not isinstance(timestamp, str):
        raise ValueError("telemetry timestamp must be an ISO 8601 UTC string")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("telemetry timestamp must be valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("telemetry timestamp must be UTC")
    return parsed


def process_dataset_windows(
    dataset: SyntheticDataset,
    config: WindowProcessingConfig,
) -> tuple[WindowFrame, ...]:
    """Partition data first, then process each run causally with isolated state."""
    manifest_runs = dataset.manifest.get("runs")
    if not isinstance(manifest_runs, list) or not manifest_runs:
        raise ValueError("dataset manifest must contain runs")
    partitions: dict[str, DatasetPartition] = {}
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

    samples_by_run: dict[str, list[dict[str, object]]] = {}
    for telemetry in dataset.telemetry:
        run_id = telemetry.get("run_id")
        if run_id not in partitions:
            raise ValueError("telemetry run is missing from manifest partitions")
        samples_by_run.setdefault(run_id, []).append(telemetry)

    frames: list[WindowFrame] = []
    for run_id, samples in samples_by_run.items():
        samples.sort(key=lambda item: _parse_utc(item.get("timestamp")))
        if not samples:
            continue
        profile = samples[0].get("profile")
        if any(sample.get("profile") != profile for sample in samples):
            raise ValueError(f"run {run_id} mixes profiles")
        solar_classifier = (
            SolarRegimeClassifier(config.solar)
            if profile == "solar_utility"
            else None
        )
        nb_classifier = (
            NBRegimeClassifier(config.nb) if profile == "ev_nb" else None
        )
        if solar_classifier is None and nb_classifier is None:
            raise ValueError(f"run {run_id} has an unsupported profile")
        buffer = TemporalWindowBuffer(config.windows)
        previous_regime = Regime.UNKNOWN
        for raw_sample in samples:
            observables = raw_sample.get("observables")
            features = raw_sample.get("features")
            if not isinstance(observables, Mapping) or not isinstance(features, Mapping):
                raise ValueError("telemetry observables and features must be objects")
            timestamp = _parse_utc(raw_sample.get("timestamp"))
            next_expected_interval_ms = raw_sample.get("next_expected_interval_ms")
            if next_expected_interval_ms is not None and (
                isinstance(next_expected_interval_ms, bool)
                or not isinstance(next_expected_interval_ms, int)
                or next_expected_interval_ms <= 0
            ):
                raise ValueError(
                    "next_expected_interval_ms must be a positive integer or null"
                )
            if solar_classifier is not None:
                irradiance = observables.get("irradiance_w_m2")
                regime = solar_classifier.update(
                    timestamp,
                    irradiance if isinstance(irradiance, (int, float)) else None,
                )
            else:
                ev_power = observables.get("ev_power_kw")
                session_active = observables.get("ev_session_active")
                regime = nb_classifier.update(
                    timestamp,
                    session_active if isinstance(session_active, bool) else None,
                    ev_power if isinstance(ev_power, (int, float)) else None,
                )
            inference_sample = WindowSample(
                schema_version=raw_sample["schema_version"],
                run_id=raw_sample["run_id"],
                sample_index=raw_sample["sample_index"],
                timestamp=timestamp,
                asset_id=raw_sample["asset_id"],
                profile=profile,
                observables=observables,
                features=features,
                next_expected_interval_s=(
                    next_expected_interval_ms / 1000
                    if next_expected_interval_ms is not None
                    else None
                ),
            )
            buffer.append(inference_sample, partitions[run_id])
            if regime == Regime.UNKNOWN:
                previous_regime = regime
                continue
            duration_s = config.windows.duration_for(regime)
            transition = regime != previous_regime
            selection = buffer.select(
                duration_s,
                minimum_samples=config.windows.minimum_samples_for(regime),
                force=transition,
            )
            if selection.status != WindowStatus.NOT_DUE:
                frames.append(
                    WindowFrame(
                        run_id=run_id,
                        asset_id=inference_sample.asset_id,
                        timestamp=raw_sample["timestamp"],
                        regime=regime,
                        status=selection.status,
                        requested_duration_s=selection.requested_duration_s,
                        effective_duration_s=selection.effective_duration_s,
                        expected_sample_count=selection.expected_sample_count,
                        sample_indices=tuple(
                            item.sample_index for item in selection.samples
                        ),
                    )
                )
            previous_regime = regime
    return tuple(frames)


def write_window_frames(path: str, frames: Sequence[WindowFrame]) -> None:
    """Write JSONL window metadata without exposing ground-truth labels."""
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            for frame in frames:
                stream.write(
                    json.dumps(
                        frame.to_json(),
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        temporary.replace(target)
    except OSError:
        if temporary.exists():
            temporary.unlink()
        raise
