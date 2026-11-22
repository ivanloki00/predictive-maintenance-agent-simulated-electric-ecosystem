"""Chronological dataset partitioning at whole-run granularity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from types import MappingProxyType
from typing import Mapping, Sequence

from .windowing import DatasetPartition


@dataclass(frozen=True)
class RunDescriptor:
    run_id: str
    started_at: datetime

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() != timedelta(0):
            raise ValueError("started_at must be a timezone-aware UTC datetime")


def assign_run_partitions(
    runs: Sequence[RunDescriptor],
    *,
    train_fraction: float,
    validation_fraction: float,
) -> Mapping[str, DatasetPartition]:
    """Assign complete runs chronologically; ties are broken by run_id."""
    for name, fraction in (
        ("train_fraction", train_fraction),
        ("validation_fraction", validation_fraction),
    ):
        if (
            isinstance(fraction, bool)
            or not isinstance(fraction, (int, float))
            or not math.isfinite(fraction)
            or fraction <= 0
        ):
            raise ValueError(f"{name} must be finite and greater than zero")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train and validation fractions must sum to less than one")

    descriptors = tuple(runs)
    if len(descriptors) < 3:
        raise ValueError("at least three runs are required for non-empty partitions")
    run_ids = [run.run_id for run in descriptors]
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("run_id values must be unique")

    ordered = sorted(descriptors, key=lambda run: (run.started_at, run.run_id))
    train_count = max(1, math.floor(len(ordered) * train_fraction))
    validation_count = max(1, math.floor(len(ordered) * validation_fraction))
    while train_count + validation_count >= len(ordered):
        if train_count > 1:
            train_count -= 1
        elif validation_count > 1:
            validation_count -= 1
        else:
            raise ValueError("fractions cannot produce three non-empty partitions")

    assignments: dict[str, DatasetPartition] = {}
    for index, run in enumerate(ordered):
        if index < train_count:
            partition = DatasetPartition.TRAIN
        elif index < train_count + validation_count:
            partition = DatasetPartition.VALIDATION
        else:
            partition = DatasetPartition.TEST
        assignments[run.run_id] = partition
    return MappingProxyType(assignments)
