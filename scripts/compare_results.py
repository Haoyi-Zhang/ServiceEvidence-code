#!/usr/bin/env python3
"""Compare deterministic result fields, excluding explicitly named measurements."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path

MEASUREMENTS = frozenset({
    'seconds', 'reference_seconds', 'indexed_seconds', 'reference_over_indexed',
    'reference_median_ms', 'indexed_median_ms', 'paired_speedup_median',
    'paired_speedup_min', 'paired_speedup_max',
    'elapsed_seconds', 'cpu_seconds', 'peak_rss_mib', 'centralized_seconds',
    'rpc_median_ms', 'rpc_p95_ms', 'certificate_ms_median', 'certificate_ms_p95',
    'certificate_seconds', 'compaction_seconds', 'emulation_seconds',
    'generation_seconds', 'materialization_seconds', 'total_seconds',
    'generation_ms', 'verification_ms', 'generation_ms_median',
    'verification_ms_median', 'generation_ms_p95', 'verification_ms_p95',
    'median_generation_ms', 'median_verification_ms',
    'certificate_generation_median_ms', 'certificate_verification_ms',
    'certificate_verification_ms_median', 'elapsed_seconds_median',
    'rpc_p95_ms_median', 'elapsed_seconds_range', 'rpc_p95_ms_range',
    'certificate_verification_ms_range',
})

def stable(value: object) -> object:
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k not in MEASUREMENTS}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value

def read(path: Path) -> object:
    with path.open(encoding='utf-8') as stream:
        return list(csv.DictReader(stream)) if path.suffix == '.csv' else json.load(stream)

def compare(reference: Path, candidate: Path) -> dict:
    files = sorted(
        p.relative_to(reference)
        for p in reference.rglob('*')
        if p.is_file()
        and p.suffix in {'.json', '.csv'}
        and p.name not in {'reproduction.json', 'reproduction.csv'}
        and 'runtime_environment' not in p.relative_to(reference).parts
    )
    missing, different = [], []
    for rel in files:
        if not (candidate / rel).is_file():
            missing.append(rel.as_posix())
        elif stable(read(reference / rel)) != stable(read(candidate / rel)):
            different.append(rel.as_posix())
    return {'compared_files': len(files), 'missing_files': missing,
            'different_stable_files': different,
            'excluded_measurement_fields': sorted(MEASUREMENTS),
            'stable_results_equal': not missing and not different}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    if not args.reference.is_dir() or not args.candidate.is_dir():
        parser.error('Both arguments must be result directories.')
    outcome = compare(args.reference, args.candidate)
    print(json.dumps(outcome, indent=2))
    raise SystemExit(0 if outcome['stable_results_equal'] else 1)
