#!/usr/bin/env python3
"""Capture a bounded, non-identifying execution-environment record for future runs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
from typing import Any


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def first_cpu_model() -> str | None:
    text = read_text(Path("/proc/cpuinfo"))
    if text is None:
        return None
    lines = text.splitlines()
    # Prefer descriptive hardware fields.  Numeric `processor: 0` indices are
    # only a last-resort fallback on architectures without model-name fields.
    for prefix in ("model name", "hardware", "processor"):
        for line in lines:
            if line.lower().startswith(prefix) and ":" in line:
                value = line.split(":", 1)[1].strip()
                if value and (prefix != "processor" or not value.isdigit()):
                    return value
    return None


def os_release() -> dict[str, str]:
    text = read_text(Path("/etc/os-release"))
    values: dict[str, str] = {}
    if text:
        for line in text.splitlines():
            if "=" not in line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values


def command_output(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def cgroup_value(*paths: str) -> str | None:
    for name in paths:
        value = read_text(Path(name))
        if value is not None:
            return value
    return None


def memory_total_bytes() -> int | None:
    text = read_text(Path("/proc/meminfo"))
    if text:
        for line in text.splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    return None


def filesystem_record(target: Path) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "path_role": "artifact results directory",
        "filesystem_type": None,
        "mount_source": None,
        "mount_options": None,
        "persistence_medium": "unknown",
    }
    output = command_output(["findmnt", "-T", str(target), "-n", "-o", "FSTYPE,SOURCE,OPTIONS"])
    if output:
        fields = output.split(maxsplit=2)
        if fields:
            record["filesystem_type"] = fields[0]
        if len(fields) > 1:
            record["mount_source"] = fields[1]
        if len(fields) > 2:
            # Keep only semantics relevant to persistence.  Overlay lower/upper
            # paths can contain host-specific opaque identifiers and are not
            # needed to interpret the experiment.
            allowed_prefixes = (
                "rw", "ro", "sync", "async", "relatime", "noatime",
                "dirsync", "data=", "barrier", "nobarrier", "discard",
                "nodiscard", "fsync=",
            )
            options = [
                option
                for option in fields[2].split(",")
                if any(
                    option == prefix or option.startswith(prefix)
                    for prefix in allowed_prefixes
                )
            ]
            record["mount_options"] = ",".join(options) or None
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--storage-path", type=Path)
    args = parser.parse_args()

    affinity = None
    if hasattr(os, "sched_getaffinity"):
        try:
            affinity = sorted(os.sched_getaffinity(0))
        except OSError:
            affinity = None

    cpu_max = cgroup_value("/sys/fs/cgroup/cpu.max")
    cpuset = cgroup_value(
        "/sys/fs/cgroup/cpuset.cpus.effective",
        "/sys/fs/cgroup/cpuset/cpuset.cpus",
    )
    memory_max = cgroup_value(
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
    )
    virtualization = command_output(["systemd-detect-virt", "--container"])
    if virtualization is None:
        virtualization = command_output(["systemd-detect-virt"])

    soft_as, hard_as = resource.getrlimit(resource.RLIMIT_AS)
    release = os_release()
    storage_path = args.storage_path or args.output.parent
    record = {
        "schema": 1,
        "context": args.context,
        "scope_note": (
            "This record describes the execution that creates it. It does not "
            "retroactively identify hardware or software for retained historical timings."
        ),
        "cpu": {
            "model": first_cpu_model(),
            "logical_cores_visible": os.cpu_count(),
            "affinity_cpu_count": len(affinity) if affinity is not None else None,
            "affinity_cpu_ids": affinity,
            "cgroup_cpu_max": cpu_max,
            "cgroup_cpuset": cpuset,
        },
        "memory": {
            "host_visible_total_bytes": memory_total_bytes(),
            "cgroup_memory_max": memory_max,
            "rlimit_address_space_soft": None if soft_as == resource.RLIM_INFINITY else soft_as,
            "rlimit_address_space_hard": None if hard_as == resource.RLIM_INFINITY else hard_as,
        },
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "distribution": release.get("PRETTY_NAME"),
        },
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "executable_basename": Path(sys.executable).name,
        },
        "container_or_virtualization": virtualization or "unknown",
        "persistence": filesystem_record(storage_path),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Captured environment for {args.context}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
