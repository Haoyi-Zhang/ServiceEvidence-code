"""Bounded loopback TCP evidence service and peer-driven anti-entropy.

Each Service owns one replica. Peers exchange inventory and admissible deltas;
there is no global observation list in the reconciliation path. The transport
is a trusted local experimental interface, not an Internet-facing API.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import struct
import time
from typing import Any

from .model import EvidenceCell, Replica

FRAME_LIMIT = 4 * 1024 * 1024
CELL_LIMIT = 10_000
HANDLE_LIMIT = 30_000
RPC_TIMEOUT = 10.0


def encode_json(value: Any) -> bytes:
    """Return the canonical JSON bytes used by every frame."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def pack(value: Any) -> bytes:
    data = encode_json(value)
    if len(data) > FRAME_LIMIT:
        raise ValueError("frame exceeds bounded service limit")
    return struct.pack("!I", len(data)) + data


def evidence_key(raw: dict[str, Any]) -> list[Any]:
    """Reference one evidence cell already present in the coupled state."""
    return [raw["left"], raw["right"], raw["epoch"], raw["source"]]


def compact_certificate(certificate: dict[str, Any]) -> dict[str, Any]:
    """Deduplicate evidence bodies against the state carried in the same reply.

    The ordinary certificate remains the canonical artifact representation.  This
    transport-only form replaces repeated evidence cells with immutable keys that
    the independent checker resolves from the coupled state.
    """
    kind = certificate.get("kind")
    if kind == "same":
        support = []
        for item in certificate["support"]:
            support.append(
                {
                    "pair": item["pair"],
                    "epoch": item["epoch"],
                    "cell_keys": [evidence_key(cell) for cell in item["cells"]],
                }
            )
        return {
            "kind": "same",
            "query": certificate["query"],
            "path": certificate["path"],
            "support": support,
            "evidence_encoding": "state-cell-keys",
        }
    if kind == "different":
        return {
            "kind": "different",
            "query": certificate["query"],
            "separator_pair": certificate["separator_pair"],
            "cell_key": evidence_key(certificate["cell"]),
            "evidence_encoding": "state-cell-keys",
        }
    # Ambiguity plans contain source positions but no repeated reason strings.
    return certificate


def bounded_response(request: dict[str, Any], result: dict[str, Any]) -> bytes:
    """Pack a successful response, compacting query evidence when necessary.

    If even the state-key form does not fit, return a small explicit rejection.
    The server never begins a frame that it cannot complete.
    """
    answer = {"ok": True, "result": result}
    try:
        return pack(answer)
    except ValueError:
        if (
            request.get("op") == "query"
            and isinstance(result, dict)
            and isinstance(result.get("state"), dict)
            and isinstance(result.get("certificate"), dict)
        ):
            compact = {
                "state": result["state"],
                "certificate": compact_certificate(result["certificate"]),
            }
            try:
                return pack({"ok": True, "result": compact})
            except ValueError:
                pass
        return pack({"ok": False, "error": "response exceeds bounded service limit"})


async def receive(reader: asyncio.StreamReader) -> tuple[Any, int]:
    header = await reader.readexactly(4)
    size = struct.unpack("!I", header)[0]
    if size > FRAME_LIMIT:
        raise ValueError("frame exceeds bounded service limit")
    raw = await reader.readexactly(size)
    value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if not isinstance(value, dict):
        raise ValueError("request or response must be an object")
    return value, size + 4


@dataclass
class WireStats:
    requests: int = 0
    request_bytes: int = 0
    response_bytes: int = 0
    latency_ms: list[float] = field(default_factory=list)
    commits: int = 0
    snapshot_bytes: int = 0
    fsyncs: int = 0
    certificate_generations: int = 0
    certificate_generation_ms: list[float] = field(default_factory=list)
    request_cap: int = 5_000
    byte_cap: int = 100 * 1024 * 1024

    @property
    def total_bytes(self) -> int:
        return self.request_bytes + self.response_bytes


async def rpc(port: int, request: dict, stats: WireStats | None = None) -> dict:
    """One bounded RPC; the host cannot be changed from loopback."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid loopback port")
    payload = pack(request)
    if stats and (stats.requests >= stats.request_cap or stats.total_bytes + len(payload) > stats.byte_cap):
        raise RuntimeError("wire campaign cap reached")
    started = time.perf_counter()
    reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), RPC_TIMEOUT)
    try:
        writer.write(payload)
        await asyncio.wait_for(writer.drain(), RPC_TIMEOUT)
        if stats:
            stats.requests += 1
            stats.request_bytes += len(payload)
        response, length = await asyncio.wait_for(receive(reader), RPC_TIMEOUT)
        if stats:
            stats.response_bytes += length
            stats.latency_ms.append((time.perf_counter() - started) * 1000)
            if stats.total_bytes > stats.byte_cap:
                raise RuntimeError("wire campaign byte cap reached")
        if response.get("ok") is not True:
            raise ValueError(response.get("error", "RPC rejected"))
        return response["result"]
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), RPC_TIMEOUT)
        except (ConnectionError, OSError, asyncio.TimeoutError):
            pass


def fsync_directory(path: Path) -> None:
    """Persist a completed rename in its parent directory on POSIX filesystems."""
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def cell_key(cell: EvidenceCell) -> tuple:
    return cell.left, cell.right, cell.epoch, cell.source


def sealed_report(replica: Replica) -> list[list]:
    return [[pair[0], pair[1], epoch]
            for pair, epochs in sorted(replica.relation_epochs().items())
            for epoch, cells in sorted(epochs.items())
            if set(cells) == set(replica.sources)]


def common_floor_reports(reports: list[list[list]]) -> list[list]:
    """Intersection of concrete sealed keys, not a minimum of maxima."""
    if not reports:
        return []
    common = set(map(tuple, reports[0]))
    for report in reports[1:]:
        common.intersection_update(map(tuple, report))
    greatest = {}
    for left, right, epoch in common:
        greatest[left, right] = max(greatest.get((left, right), -1), epoch)
    return [[left, right, epoch] for (left, right), epoch in sorted(greatest.items())]


def parse_floors(raw: Any) -> dict:
    if not isinstance(raw, list) or len(raw) > CELL_LIMIT:
        raise ValueError("floors must be a bounded list")
    result = {}
    for row in raw:
        if (not isinstance(row, list) or len(row) != 3
                or not all(isinstance(x, str) and x for x in row[:2])
                or row[0] >= row[1] or type(row[2]) is not int or row[2] < 0
                or tuple(row[:2]) in result):
            raise ValueError("invalid floor proposal")
        result[tuple(row[:2])] = row[2]
    return result


class Service:
    def __init__(self, node_id: str, sources: list[str], threshold: int,
                 handles: list[str], members: list[str], snapshot: Path,
                 stats: WireStats | None = None):
        if len(set(members)) != len(members) or node_id not in members or not 1 <= len(members) <= 6:
            raise ValueError("invalid fixed membership")
        self.members = tuple(sorted(members))
        self.snapshot = snapshot
        self.stats = stats
        self.replica = Replica(node_id, sources, threshold, handles)
        self.server = None
        self.port = None
        if snapshot.exists():
            saved = Replica.import_state(json.loads(snapshot.read_text(encoding="utf-8")))
            if (saved.node_id, saved.sources, saved.threshold) != (node_id, self.replica.sources, threshold):
                raise ValueError("persistent configuration mismatch")
            self.replica = saved
        # A pre-rename temporary file can survive an abrupt exit.  It was never
        # acknowledged and therefore is not a committed snapshot.
        snapshot.with_suffix(".pending").unlink(missing_ok=True)
        self._admit(self.replica)

    @staticmethod
    def _admit(replica: Replica) -> None:
        if len(replica) > CELL_LIMIT or len(replica.handles) > HANDLE_LIMIT:
            raise ValueError("service state cap reached")
        pack(replica.export_state())

    def _commit(self, proposed: Replica) -> None:
        self._admit(proposed)
        # No await in this method: requests cannot observe a partial transition.
        raw = json.dumps(proposed.export_state(), sort_keys=True, separators=(",", ":"))
        self.snapshot.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.snapshot.with_suffix(".pending")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.snapshot)
            # Once replace succeeds, the path and in-memory view advance
            # together.  A subsequent directory-fsync failure is reported to
            # the client as an unacknowledged/ambiguous outcome; idempotent
            # retry is required, but this process does not continue from a
            # state older than the file it can already read.
            self.replica = proposed
            fsync_directory(self.snapshot.parent)
            if self.stats is not None:
                self.stats.commits += 1
                self.stats.snapshot_bytes += len(raw.encode("utf-8"))
                # One fsync persists file contents and one persists the rename.
                self.stats.fsyncs += 2
        finally:
            temporary.unlink(missing_ok=True)

    async def start(self, port: int = 0) -> int:
        self.server = await asyncio.start_server(self._connection, "127.0.0.1", port)
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def _connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request, _ = await asyncio.wait_for(receive(reader), RPC_TIMEOUT)
            result = await self.dispatch(request)
            payload = bounded_response(request, result)
        except (ValueError, KeyError, TypeError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            payload = pack({"ok": False, "error": "invalid, unavailable, or incompatible request"})
        try:
            writer.write(payload)
            await asyncio.wait_for(writer.drain(), RPC_TIMEOUT)
        except (ConnectionError, OSError, asyncio.TimeoutError):
            pass
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), RPC_TIMEOUT)
            except (ConnectionError, OSError, asyncio.TimeoutError):
                pass

    async def dispatch(self, request: dict) -> dict:
        op = request.get("op")
        if op == "state":
            return self.replica.export_state()
        if op == "query":
            # There is no await between construction of the answer and its
            # explicit state, so both describe one local snapshot.
            started = time.perf_counter()
            certificate = self.replica.certificate(request["left"], request["right"])
            if self.stats is not None:
                self.stats.certificate_generations += 1
                self.stats.certificate_generation_ms.append(
                    (time.perf_counter() - started) * 1000.0
                )
            return {"state": self.replica.export_state(), "certificate": certificate}
        if op == "report":
            return {"member": self.replica.node_id, "sources": list(self.replica.sources),
                    "threshold": self.replica.threshold, "sealed": sealed_report(self.replica)}
        if op == "inventory":
            return {"keys": [list(cell_key(c)) for c in self.replica.cells],
                    "sources": list(self.replica.sources), "threshold": self.replica.threshold,
                    "floors": self.replica.export_state()["stable_floors"]}
        if op == "fetch":
            raw_keys = request.get("keys")
            if not isinstance(raw_keys, list) or len(raw_keys) > CELL_LIMIT:
                raise ValueError("keys must be a bounded list")
            wanted = set()
            for key in raw_keys:
                if (not isinstance(key, list) or len(key) != 4
                        or not all(isinstance(key[i], str) and key[i] for i in (0, 1, 3))
                        or key[0] >= key[1] or type(key[2]) is not int or key[2] < 0):
                    raise ValueError("invalid requested cell key")
                wanted.add(tuple(key))
            state = self.replica.export_state()
            floors = self.replica.stable_floors
            state["cells"] = [c.to_dict() for c in self.replica.cells
                              if cell_key(c) in wanted or c.epoch == floors.get(c.pair, -1)]
            return state
        if op in ("merge", "ingest"):
            proposed = Replica.import_state(self.replica.export_state())
            if op == "merge":
                proposed.join(Replica.import_state(request["state"]))
            else:
                raw_cells = request.get("cells")
                if not isinstance(raw_cells, list) or len(raw_cells) > CELL_LIMIT:
                    raise ValueError("cells must be a bounded list")
                for raw in raw_cells:
                    proposed.add(EvidenceCell.from_dict(raw))
            self._commit(proposed)
            return {"cells": len(proposed)}
        if op == "pull":
            peer = request["peer_port"]
            remote = await rpc(peer, {"op": "inventory"}, self.stats)
            if (remote["sources"], remote["threshold"]) != (list(self.replica.sources), self.replica.threshold):
                raise ValueError("peer configuration mismatch")
            own = {cell_key(c) for c in self.replica.cells}
            missing = [key for key in remote["keys"] if tuple(key) not in own]
            # Fetch even an empty difference: a peer floor may be newer, and
            # handles or a complete floor vector still need to propagate.
            delta = await rpc(peer, {"op": "fetch", "keys": missing}, self.stats)
            proposed = Replica.import_state(self.replica.export_state())
            proposed.join(Replica.import_state(delta))
            self._commit(proposed)
            return {"requested_cells": len(missing), "cells": len(proposed)}
        if op == "ack":
            floors = parse_floors(request.get("floors"))
            grouped = self.replica.relation_epochs()
            vectors = []
            for pair, epoch in sorted(floors.items()):
                vector = grouped.get(pair, {}).get(epoch, {})
                if set(vector) != set(self.replica.sources):
                    raise ValueError("cannot acknowledge an absent sealed vector")
                vectors.extend(vector[s].to_dict() for s in self.replica.sources)
            return {"member": self.replica.node_id, "floors": request["floors"], "vectors": vectors}
        if op == "compact":
            floors = parse_floors(request.get("floors"))
            acks = request.get("acks")
            if not isinstance(acks, list) or len(acks) != len(self.members):
                raise ValueError("all fixed members must acknowledge")
            if any(not isinstance(a, dict) for a in acks):
                raise ValueError("invalid acknowledgement")
            if sorted(a.get("member", "") for a in acks) != list(self.members):
                raise ValueError("missing or duplicate member acknowledgement")
            local = await self.dispatch({"op": "ack", "floors": request["floors"]})
            for ack in acks:
                if ack.get("floors") != local["floors"] or ack.get("vectors") != local["vectors"]:
                    raise ValueError("acknowledged vectors disagree")
            pending = request.get("pending", 1)
            if type(pending) is not int or pending < 0:
                raise ValueError("invalid pending allowance")
            proposed = Replica.import_state(self.replica.export_state())
            removed = proposed.compact(floors, pending)
            self._commit(proposed)
            return {"removed": removed, "cells": len(proposed)}
        raise ValueError("unknown operation")


async def run_node(args: argparse.Namespace) -> None:
    service = Service(args.node, args.sources.split(","), args.threshold, [],
                      args.members.split(","), Path(args.snapshot))
    await service.start(args.port)
    print(json.dumps({"port": service.port, "node": args.node}), flush=True)
    try:
        await service.server.serve_forever()
    finally:
        await service.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True)
    parser.add_argument("--members", required=True, help="comma-separated fixed node identifiers")
    parser.add_argument("--sources", default="v0,v1,v2,v3,v4")
    parser.add_argument("--threshold", type=int, default=2)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between zero and 65535")
    asyncio.run(run_node(args))


if __name__ == "__main__":
    main()
