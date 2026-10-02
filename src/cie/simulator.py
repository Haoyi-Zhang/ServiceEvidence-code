"""Deterministic network-fault emulator for evidence delivery."""

from __future__ import annotations

from dataclasses import dataclass
import json
import random
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .model import EvidenceCell, Relation, Replica


@dataclass(frozen=True)
class Delivery:
    step: int
    destination: str
    cell: EvidenceCell
    duplicate: bool
    repair: bool


@dataclass(frozen=True)
class SimulationResult:
    replicas: Mapping[str, Replica]
    deliveries: Tuple[Delivery, ...]
    scheduled_messages: int
    delivered_messages: int
    repair_messages: int
    duplicate_messages: int
    payload_bytes: int
    convergence_step: int
    pre_repair_converged: bool


def _cell_bytes(cell: EvidenceCell) -> int:
    return len(
        json.dumps(cell.to_dict(), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def emulate(
    cells: Sequence[EvidenceCell],
    node_ids: Sequence[str],
    sources: Sequence[str],
    threshold: int = 2,
    seed: int = 1,
    loss_rate: float = 0.05,
    duplicate_rate: float = 0.08,
    partition_fraction: float = 0.40,
    repair: bool = True,
    delivery_cap: int = 500_000,
    handles: Optional[Sequence[str]] = None,
) -> SimulationResult:
    """Broadcast cells under delay, loss, duplication, and a temporary partition.

    Initial deliveries are randomly ordered. An idealized oracle-repair phase
    sends globally known missing cells when ``repair`` is true. It is not a
    peer-to-peer anti-entropy implementation; see the separate TCP service.
    """
    for name, value in {
        "loss_rate": loss_rate,
        "duplicate_rate": duplicate_rate,
        "partition_fraction": partition_fraction,
    }.items():
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must lie in [0,1]")
    if not node_ids:
        raise ValueError("at least one node is required")

    rng = random.Random(seed)
    nodes = tuple(node_ids)
    replicas = {
        node: Replica(node, sources, threshold, handles=handles) for node in nodes
    }
    scheduled: List[Tuple[str, EvidenceCell, bool]] = []
    for cell in cells:
        for destination in nodes:
            scheduled.append((destination, cell, False))
            if rng.random() < duplicate_rate:
                scheduled.append((destination, cell, True))
    rng.shuffle(scheduled)

    # During the early portion, messages crossing two deterministic node groups
    # are withheld as a partition.  Since cells have no source node in this
    # broadcast model, the cell's source identifier selects a notional origin.
    split = max(1, len(nodes) // 2)
    left_nodes = set(nodes[:split])
    source_side = {source: (index % 2 == 0) for index, source in enumerate(sorted(sources))}
    partition_steps = int(len(scheduled) * partition_fraction)

    deliveries: List[Delivery] = []
    payload_bytes = 0
    duplicates = 0
    initial_scheduled = len(cells) * len(nodes)
    for index, (destination, cell, is_duplicate) in enumerate(scheduled):
        origin_left = source_side[cell.source]
        crosses = (destination in left_nodes) != origin_left
        if index < partition_steps and crosses:
            continue
        if rng.random() < loss_rate:
            continue
        if len(deliveries) >= delivery_cap:
            raise RuntimeError("delivery cap exceeded")
        replicas[destination].add(cell)
        deliveries.append(
            Delivery(
                step=len(deliveries),
                destination=destination,
                cell=cell,
                duplicate=is_duplicate,
                repair=False,
            )
        )
        payload_bytes += _cell_bytes(cell)
        duplicates += int(is_duplicate)

    states = [replica.cells for replica in replicas.values()]
    pre_repair_converged = all(state == states[0] for state in states[1:])

    repair_messages = 0
    if repair:
        retained = tuple(sorted(set(cells)))
        for destination in nodes:
            replica = replicas[destination]
            present = set(replica.cells)
            missing = [cell for cell in retained if cell not in present]
            for cell in missing:
                if len(deliveries) >= delivery_cap:
                    raise RuntimeError("delivery cap exceeded during repair")
                replica.add(cell)
                deliveries.append(
                    Delivery(
                        step=len(deliveries),
                        destination=destination,
                        cell=cell,
                        duplicate=False,
                        repair=True,
                    )
                )
                payload_bytes += _cell_bytes(cell)
                repair_messages += 1

    final_states = [replica.cells for replica in replicas.values()]
    convergence_step = len(deliveries) if all(
        state == final_states[0] for state in final_states[1:]
    ) else -1
    return SimulationResult(
        replicas=replicas,
        deliveries=tuple(deliveries),
        scheduled_messages=initial_scheduled,
        delivered_messages=len(deliveries),
        repair_messages=repair_messages,
        duplicate_messages=duplicates,
        payload_bytes=payload_bytes,
        convergence_step=convergence_step,
        pre_repair_converged=pre_repair_converged,
    )


def stable_epochs(replicas: Mapping[str, Replica]) -> Dict[Relation, int]:
    """Greatest actually retained sealed epoch common to all replicas.

    A minimum of latest sealed epochs is insufficient: histories may have holes.
    This helper observes full local states; a network implementation must obtain
    the corresponding reports and acknowledgements through its protocol.
    """
    if not replicas:
        return {}
    states = list(replicas.values())
    configuration = (states[0].sources, states[0].threshold)
    common = None
    for replica in states:
        if (replica.sources, replica.threshold) != configuration:
            raise ValueError("replica configurations differ")
        sealed = {(pair, epoch) for pair, epochs in replica.relation_epochs().items()
                  for epoch, cells in epochs.items() if set(cells) == set(replica.sources)}
        common = sealed if common is None else common & sealed
    stable: Dict[Relation, int] = {}
    for pair, epoch in common or ():
        stable[pair] = max(stable.get(pair, -1), epoch)
    return stable
