"""Generate and evaluate a small, explicitly synthetic Freesun/NB dataset."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import uuid

from .baseline import RCBaselineConfig, evaluate_rc_baseline
from .evaluation import EvaluationConfig
from .pipeline import (
    WindowProcessingConfig,
    process_dataset_windows,
    write_window_frames,
)
from .simulator import (
    DegradationMode,
    SyntheticDataset,
    SyntheticRunConfig,
    generate_dataset,
    write_dataset,
)
from .windowing import (
    NBRegimeConfig,
    Regime,
    SolarRegimeConfig,
    WindowingConfig,
)


def build_demo_runs(seed: int) -> list[SyntheticRunConfig]:
    run_id_rng = random.Random(seed)
    scenarios = (
        ("solar_utility", DegradationMode.NONE, 1000.0),
        ("ev_nb", DegradationMode.NONE, 120.0),
        ("solar_utility", DegradationMode.IGBT_THERMAL_FATIGUE, 1000.0),
        ("ev_nb", DegradationMode.DC_LINK_CAPACITOR, 120.0),
        ("solar_utility", DegradationMode.INSULATION, 1000.0),
        ("ev_nb", DegradationMode.INSULATION, 120.0),
    )
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    runs = []
    for index, (profile, mode, nominal_power_kw) in enumerate(scenarios):
        run_id = str(uuid.UUID(int=run_id_rng.getrandbits(128), version=4))
        runs.append(
            SyntheticRunConfig(
                run_id=run_id,
                asset_id=f"{'FREESUN' if profile == 'solar_utility' else 'NB'}-SYN-{index + 1:02d}",
                profile=profile,
                seed=seed + index,
                started_at=start + timedelta(days=index),
                duration_s=300,
                physical_step_ms=250,
                sampling_period_ms=1000,
                prediction_horizon_s=120,
                degradation_mode=mode,
                degradation_onset_fraction=0.5,
                ambient_temperature_c=25,
                sensor_noise_stddev=0.5,
                nominal_power_kw=nominal_power_kw,
                thermal_time_constant_s=75,
                temperature_rise_at_full_load_c=25,
                insulation_baseline_megaohm=50,
                esr_baseline_mohm=2,
                thermal_failure_threshold_c=135,
                esr_failure_ratio=3,
                insulation_failure_megaohm=0.1,
            )
        )
    return runs


def run_demo(output_dir: Path, seed: int) -> dict[str, object]:
    runs = build_demo_runs(seed)
    dataset = generate_dataset(
        runs, train_fraction=0.5, validation_fraction=1 / 6
    )
    window_config = WindowProcessingConfig(
        solar=SolarRegimeConfig(
            irradiance_on_w_m2=200,
            irradiance_off_w_m2=100,
            debounce_s=2,
        ),
        nb=NBRegimeConfig(ramp_threshold_kw_per_s=5, debounce_s=2),
        windows=WindowingConfig(
            sampling_period_ms=1000,
            max_gap_s=2,
            max_history_s=60,
            stride_s=30,
            max_samples=61,
            durations_s={
                Regime.SOLAR_ACTIVE: 30,
                Regime.SOLAR_LOW: 30,
                Regime.IDLE: 30,
                Regime.CHARGING_STEADY: 30,
                Regime.CHARGING_RAMP: 30,
            },
        ),
    )
    frames = process_dataset_windows(dataset, window_config)
    dataset = SyntheticDataset(
        telemetry=dataset.telemetry,
        labels=dataset.labels,
        manifest={
            **dataset.manifest,
            "windowing": window_config.as_manifest(),
        },
    )
    baseline_config = RCBaselineConfig(
        nominal_power_kw={"solar_utility": 1000, "ev_nb": 120},
        temperature_rise_at_full_load_c=25,
        thermal_time_constant_s=75,
    )
    baseline_manifest = {
        "parameters": {
            "nominal_power_kw": {
                "value": dict(baseline_config.nominal_power_kw),
                "unit": "kW",
                "meaning": "nominal load by synthetic profile",
            },
            "temperature_rise_at_full_load_c": {
                "value": baseline_config.temperature_rise_at_full_load_c,
                "unit": "degC",
                "meaning": "RC baseline temperature rise at full load",
            },
            "thermal_time_constant_s": {
                "value": baseline_config.thermal_time_constant_s,
                "unit": "s",
                "meaning": "RC baseline response time constant",
            },
        },
        "source": "synthetic demo configuration",
        "confidence": "low",
        "status": "synthetic_unvalidated",
    }
    evaluation_config = EvaluationConfig(
        forecast_horizon_s=120,
        thermal_threshold_c=70,
        alarm_cooldown_s=30,
    )
    evaluation_manifest = {
        "forecast_horizon_s": {
            "value": evaluation_config.forecast_horizon_s,
            "unit": "s",
            "meaning": "persistence forecast target horizon",
            "source": "synthetic demo configuration",
            "confidence": "low",
            "status": "synthetic_unvalidated",
        },
        "thermal_threshold_c": {
            "value": evaluation_config.thermal_threshold_c,
            "unit": "degC",
            "meaning": "synthetic threshold applied to persistence forecast",
            "source": "synthetic demo configuration",
            "confidence": "low",
            "status": "synthetic_unvalidated",
        },
        "alarm_cooldown_s": {
            "value": evaluation_config.alarm_cooldown_s,
            "unit": "s",
            "meaning": "alarm grouping cooldown for event scoring",
            "source": "synthetic demo configuration",
            "confidence": "low",
            "status": "synthetic_unvalidated",
        },
        "alarm_rule": (
            "raise when the persistence forecast is at or above "
            "thermal_threshold_c; group alarms using alarm_cooldown_s"
        ),
        "event_costs": (
            asdict(evaluation_config.event_costs)
            if evaluation_config.event_costs is not None
            else None
        ),
    }
    dataset = SyntheticDataset(
        telemetry=dataset.telemetry,
        labels=dataset.labels,
        manifest={
            **dataset.manifest,
            "evaluation": evaluation_manifest,
            "baseline": baseline_manifest,
        },
    )
    baseline = evaluate_rc_baseline(
        dataset,
        baseline_config=baseline_config,
        evaluation_config=evaluation_config,
        solar_regime_config=window_config.solar,
        nb_regime_config=window_config.nb,
    )
    write_dataset(dataset, output_dir)
    write_window_frames(str(output_dir / "windows.jsonl"), frames)
    report: dict[str, object] = {
        "synthetic_unvalidated": True,
        "seed": seed,
        "test_run_count": baseline.test_run_count,
        "baseline_config": {
            "nominal_power_kw": dict(baseline_config.nominal_power_kw),
            "temperature_rise_at_full_load_c": baseline_config.temperature_rise_at_full_load_c,
            "thermal_time_constant_s": baseline_config.thermal_time_constant_s,
            "parameter_status": baseline_manifest["status"],
            "parameter_provenance": {
                "source": "synthetic demo configuration",
                "confidence": "low",
                "status": "synthetic_unvalidated",
                "units": {
                    "nominal_power_kw": "kW",
                    "temperature_rise_at_full_load_c": "degC",
                    "thermal_time_constant_s": "s",
                },
            },
        },
        "evaluation_config": asdict(evaluation_config),
        "windowing_config": window_config.as_manifest(),
        "temperature_metrics": asdict(baseline.temperature_metrics),
        "forecast_temperature_metrics": (
            asdict(baseline.forecast_temperature_metrics)
            if baseline.forecast_temperature_metrics is not None
            else None
        ),
        "temperature_metrics_by_profile": {
            profile: asdict(metrics)
            for profile, metrics in baseline.temperature_metrics_by_profile.items()
        },
        "temperature_metrics_by_scenario": {
            scenario: asdict(metrics)
            for scenario, metrics in baseline.temperature_metrics_by_scenario.items()
        },
        "temperature_metrics_by_regime": {
            regime: asdict(metrics)
            for regime, metrics in baseline.temperature_metrics_by_regime.items()
        },
        "forecast_temperature_metrics_by_profile": {
            profile: asdict(metrics)
            for profile, metrics in baseline.forecast_temperature_metrics_by_profile.items()
        },
        "forecast_temperature_metrics_by_scenario": {
            scenario: asdict(metrics)
            for scenario, metrics in baseline.forecast_temperature_metrics_by_scenario.items()
        },
        "forecast_temperature_metrics_by_regime": {
            regime: asdict(metrics)
            for regime, metrics in baseline.forecast_temperature_metrics_by_regime.items()
        },
        "event_metrics": asdict(baseline.event_metrics),
        "event_metrics_by_profile": {
            profile: asdict(metrics)
            for profile, metrics in baseline.event_metrics_by_profile.items()
        },
        "event_metrics_by_scenario": {
            scenario: asdict(metrics)
            for scenario, metrics in baseline.event_metrics_by_scenario.items()
        },
        "event_cost_config": (
            asdict(evaluation_config.event_costs)
            if evaluation_config.event_costs is not None
            else None
        ),
        "event_cost_status": (
            "configured_with_source_and_rationale"
            if evaluation_config.event_costs is not None
            else "not_aggregated_without_justified_weights"
        ),
    }
    report_path = output_dir / "evaluation.json"
    temporary = report_path.with_suffix(".json.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
        temporary.replace(report_path)
    except OSError:
        if temporary.exists():
            temporary.unlink()
        raise
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="directory for telemetry.jsonl, labels.jsonl, manifest.json, and evaluation.json",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    report = run_demo(args.output, args.seed)
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
