"""Conservative adapter for the supplied public HTTP navigation extraction.

HTTP redirects and endpoint reuse create candidates, never identity votes.
Only the first source denotes the archived observation; all other sources emit
explicitly generated UNKNOWN closure cells. No URL is fetched by this module.
"""
import csv
from pathlib import Path
from urllib.parse import urlsplit
from .model import EvidenceCell, Vote, relation


def authority_handle(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("expected an HTTP authority without credentials")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    default = 80 if parsed.scheme == "http" else 443
    return f"{parsed.scheme}://{host}" + (f":{port}" if port and port != default else "")


def archived_candidates(path: Path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 6:
        raise ValueError("this frozen selection must contain six navigation rows")
    handles, pairs = set(), set()
    for row in rows:
        left = authority_handle(row["request_url"])
        handles.add(left)
        if row["redirect_url"]:
            if int(row["status"]) not in range(300, 400):
                raise ValueError("redirect candidate must have a redirect status")
            right = authority_handle(row["redirect_url"])
            handles.add(right)
            if left != right:
                pairs.add(relation(left, right))
    cells = []
    for left, right in sorted(pairs):
        for i in range(5):
            reason = ("archived redirect candidate; identity undetermined" if i == 0
                      else "generated closure; no independent archived observation")
            cells.append(EvidenceCell(left, right, 0, f"v{i}", Vote.UNKNOWN, reason))
    return sorted(handles), cells
