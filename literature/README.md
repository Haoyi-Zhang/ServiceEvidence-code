# Bibliography evidence snapshot

This directory makes the standalone artifact's reference audit self-contained.

- `references.bib` is the exact scholarly bibliography consumed by the paper build.
- `cited-keys.txt` lists the citation keys used by the manuscript, one per line.

When the artifact is inside the full project, `scripts/audit_bibliography.py` also verifies that these files agree with `paper/references.bib` and the citations parsed from `paper/main.tex` plus `paper/supplement-content.tex`. In the standalone repository, the same script verifies the bundled bibliography, key inventory, and `literature-calibration.csv` without requiring manuscript files.

This is a metadata and source-binding check, not certification that every
reference has been read in full. The MWS 2018 and extended author-v2 bindings
state their actual inspected scope separately.
