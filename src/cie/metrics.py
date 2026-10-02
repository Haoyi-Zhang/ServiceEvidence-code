"""Partition correctness and convergence metrics."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import comb
from typing import Mapping, Tuple

from .model import PartitionView


@dataclass(frozen=True)
class PartitionMetrics:
    false_merge_pairs: int
    false_split_pairs: int
    predicted_same_pairs: int
    true_same_pairs: int

    @property
    def false_merge_rate(self) -> float:
        return (
            self.false_merge_pairs / self.predicted_same_pairs
            if self.predicted_same_pairs
            else 0.0
        )

    @property
    def false_split_rate(self) -> float:
        return (
            self.false_split_pairs / self.true_same_pairs
            if self.true_same_pairs
            else 0.0
        )


def partition_metrics(
    view: PartitionView, truth: Mapping[str, str]
) -> PartitionMetrics:
    true_same_pairs = sum(comb(count, 2) for count in Counter(truth.values()).values())
    predicted_same_pairs = 0
    correctly_joined = 0
    for component in view.components:
        predicted_same_pairs += comb(len(component), 2)
        counts = Counter(truth[handle] for handle in component)
        correctly_joined += sum(comb(count, 2) for count in counts.values())
    return PartitionMetrics(
        false_merge_pairs=predicted_same_pairs - correctly_joined,
        false_split_pairs=true_same_pairs - correctly_joined,
        predicted_same_pairs=predicted_same_pairs,
        true_same_pairs=true_same_pairs,
    )


def partition_signature(view: PartitionView) -> Tuple[Tuple[str, ...], ...]:
    return tuple(sorted(tuple(sorted(component)) for component in view.components))
