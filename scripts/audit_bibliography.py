#!/usr/bin/env python3
"""Audit citation coverage, metadata completeness, and ledger consistency."""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT.parent / "paper"
BUNDLED_BIB = ROOT / "literature" / "references.bib"
CITATION_KEYS = ROOT / "literature" / "cited-keys.txt"
PAPER_BIB = PAPER / "references.bib"
BIB = PAPER_BIB if PAPER_BIB.exists() else BUNDLED_BIB
CALIBRATION = ROOT / "literature-calibration.csv"
TEX_FILES = (PAPER / "main.tex", PAPER / "supplement-content.tex")
DOI = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
YEAR = re.compile(r"^(19|20)\d{2}$")


class AuditError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def parse_bib(path: Path) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    current_key = ""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        header = re.match(r"^@(\w+)\{([^,]+),\s*$", line)
        if header:
            require(current is None, f"nested BibTeX entry at line {number}")
            current_key = header.group(2).strip()
            require(current_key and current_key not in entries, f"duplicate BibTeX key: {current_key}")
            current = {"entry_type": header.group(1).lower()}
            continue
        if current is None:
            require(not line.strip(), f"text outside BibTeX entry at line {number}")
            continue
        if line.strip() == "}":
            entries[current_key] = current
            current = None
            current_key = ""
            continue
        field = re.match(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*\{(.*)\},?\s*$", line)
        require(field is not None, f"unsupported BibTeX field syntax at line {number}")
        name, value = field.group(1).lower(), field.group(2).strip()
        require(name not in current, f"duplicate field {name} in {current_key}")
        require(value != "", f"empty field {name} in {current_key}")
        current[name] = value
    require(current is None, "unterminated BibTeX entry")
    return entries


def normalize_title(value: str) -> str:
    value = re.sub(r"\\[a-zA-Z]+\s*", "", value)
    value = re.sub(r"[{}\\]", "", value)
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def inventory_keys() -> set[str]:
    lines = [
        line.strip()
        for line in CITATION_KEYS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    require(len(lines) == len(set(lines)), "duplicate citation key in standalone inventory")
    return set(lines)


def manuscript_cited_keys() -> set[str] | None:
    if not all(path.exists() for path in TEX_FILES):
        return None
    text = "\n".join(path.read_text(encoding="utf-8") for path in TEX_FILES)
    require("\\nocite" not in text, "\\nocite is not permitted for count padding")
    result: set[str] = set()
    for group in re.findall(r"\\cite(?:\[[^\]]*\])?\{([^}]*)\}", text):
        result.update(piece.strip() for piece in group.split(",") if piece.strip())
    return result


def cited_keys() -> set[str]:
    inventory = inventory_keys()
    manuscript = manuscript_cited_keys()
    if manuscript is not None:
        require(manuscript == inventory, "manuscript citations and standalone citation inventory differ")
    return inventory


def calibration_rows() -> list[dict[str, str]]:
    with CALIBRATION.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames is not None, "literature calibration has no header")
        required = {
            "cite_key", "title", "authors", "year", "venue", "identifier",
            "category", "manuscript_role", "project_delta", "manuscript_location",
            "source_anchor", "verification_scope", "status",
        }
        require(required.issubset(reader.fieldnames), "literature calibration schema changed")
        rows = list(reader)
    return rows


def main() -> int:
    entries = parse_bib(BIB)
    bundled_entries = parse_bib(BUNDLED_BIB)
    require(entries == bundled_entries, "paper bibliography and standalone bibliography snapshot differ")
    citations = cited_keys()
    ledger = calibration_rows()
    ledger_keys = [row["cite_key"] for row in ledger]

    require(len(entries) >= 55, "fewer than 55 unique scholarly references")
    require(len(entries) == 68, "frozen bibliography count changed")
    require(len(set(ledger_keys)) == len(ledger_keys), "duplicate calibration cite_key")
    require(set(entries) == citations == set(ledger_keys), "BibTeX, citation, and calibration key sets differ")

    seen_titles: dict[str, str] = {}
    seen_dois: dict[str, str] = {}
    seen_roles: dict[str, str] = {}
    seen_deltas: dict[str, str] = {}
    ledger_by_key = {row["cite_key"]: row for row in ledger}
    for key, entry in entries.items():
        for required in ("author", "title", "year"):
            require(entry.get(required, "").strip(), f"{key} lacks {required}")
        require(entry.get("booktitle") or entry.get("journal"), f"{key} lacks venue")
        require(YEAR.fullmatch(entry["year"]) is not None, f"invalid year for {key}")
        title_key = normalize_title(entry["title"])
        require(title_key and title_key not in seen_titles, f"duplicate normalized title: {key}/{seen_titles.get(title_key)}")
        seen_titles[title_key] = key
        doi = entry.get("doi", "").lower()
        if doi:
            require(DOI.fullmatch(doi) is not None, f"invalid DOI syntax for {key}")
            require(doi not in seen_dois, f"duplicate DOI: {key}/{seen_dois.get(doi)}")
            seen_dois[doi] = key

        row = ledger_by_key[key]
        require(row["year"] == entry["year"], f"year mismatch for {key}")
        require(normalize_title(row["title"]) == title_key, f"title mismatch for {key}")
        require(row["authors"].strip() and row["venue"].strip(), f"incomplete ledger metadata for {key}")
        role = row["manuscript_role"].strip()
        delta = row["project_delta"].strip()
        require(len(role) >= 80 and len(delta) >= 80, f"comparison scope is too generic for {key}")
        require(row["source_anchor"].strip(), f"missing source anchor for {key}")
        require(row["manuscript_location"].strip(), f"missing manuscript location for {key}")
        require(row["status"] == "cited in manuscript", f"unexpected citation status for {key}")
        role_key = re.sub(r"\s+", " ", role.lower())
        delta_key = re.sub(r"\s+", " ", delta.lower())
        require(role_key not in seen_roles, f"duplicate manuscript role: {key}/{seen_roles.get(role_key)}")
        require(delta_key not in seen_deltas, f"duplicate project delta: {key}/{seen_deltas.get(delta_key)}")
        seen_roles[role_key] = key
        seen_deltas[delta_key] = key
        scope = row["verification_scope"].lower()
        require("metadata checked" in scope and "source anchor" in scope, f"verification scope missing for {key}")
        identifier = row["identifier"].strip()
        if doi:
            require(identifier.lower() == f"doi:{doi}", f"DOI ledger mismatch for {key}")
        else:
            require(
                "stable venue record" in identifier.lower() or identifier.startswith("https://"),
                f"non-DOI record lacks a stable venue record or URL for {key}",
            )

    print(
        f"PASS: {len(entries)} unique cited references; {len(seen_dois)} unique DOIs; "
        "BibTeX/citation/calibration sets equal in full and standalone layouts; "
        "per-paper roles and source anchors present; "
        "no nocite or duplicate title/identifier"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AuditError, OSError, csv.Error) as error:
        print(f"FAIL: {error}")
        raise SystemExit(1)
