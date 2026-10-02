# Bibliography evidence snapshot

This directory makes the standalone artifact's reference audit self-contained.

- `references.bib` is the exact scholarly bibliography consumed by the paper build.
- `cited-keys.txt` lists the 67 citation keys used by the manuscript, one per line.

When the artifact is inside the full project, `scripts/audit_bibliography.py` also verifies that these files agree with `paper/references.bib` and the citations parsed from `paper/main.tex` plus `paper/supplementary_appendix.tex`. In the standalone repository, the same script verifies the bundled bibliography, key inventory, and `literature-calibration.csv` without requiring manuscript files.
