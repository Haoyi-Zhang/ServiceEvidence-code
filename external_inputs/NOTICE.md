# Public input notices

## Web Performance Pitfalls navigation calibration

`public_http_calibration.csv` is a compact factual extraction from three sample HAR records distributed with Theresa Enghardt, Thomas Zinner, and Anja Feldmann's *Web Performance Pitfalls* measurement materials. The source project licenses its software under BSD 2-Clause; the notice is retained in `LICENSE-BSD-2-CLAUSE.txt`. The extraction contains factual navigation metadata only, not downloaded response bodies, page assets, cookies, or credentials. No blanket license over third-party page contents is inferred.

The six rows keep only request URL, status, redirect target, server address, and whole-second capture time. They calibrate the observation vocabulary and exercise the conservative UNKNOWN adapter. They are not identity labels, a multi-vantage dataset, or a prevalence sample.

Source project: https://github.com/renghardt/web-measurement-tools

Associated publication: Theresa Enghardt, Thomas Zinner, and Anja Feldmann. *Web Performance Pitfalls*. Passive and Active Measurement, pages 286--303, 2019. DOI: 10.1007/978-3-030-15986-3_19.

Reproduction reads the included extraction and does not require a new network acquisition.
The public repository paths provide source provenance; the retained access date is recorded in `../external_resources.csv`, and the extracted rows needed for reproduction are included locally.

## OONI probe/control target-equivalence fixtures

`ooni_fixture_selection.csv` records 16 inspected Web Connectivity fixture candidates in the OONI pipeline repository, 12 retained unique measurements, and four exclusions with explicit duplicate or missing-data reasons. `ooni_dual_vantage_targets.csv` is the factual, minimized extraction from the retained records. Each record pairs observations from a probe network and a control network. The retained CSV contains only the side-specific endpoint, explicit TCP outcome, HTTP status, header-name, title, failure-category, and contextual fields used by the declared benchmark. `ooni_field_mapping.csv` identifies the source path for every retained class of field and records case-specific absences or anomalies.

The extraction does not fill an absent side-specific field from another signal. In particular, match flags do not synthesize missing probe titles; DNS answers or a successful control HTTP response do not become an unreported TCP success; negative or zero status values remain missing to the predicate; and probe/control endpoint records are kept separately. Response bodies, cookies, certificates, report identifiers, probe IP placeholders, and unrelated annotations are omitted.

The OONI pipeline repository is distributed under BSD 3-Clause; its notice is retained in `LICENSE-OONI-PIPELINE-BSD-3-CLAUSE.txt`. Each retained row's `source_url` identifies the public fixture and the selection manifest covers all inspected candidates. The included extraction, mapping, and selection manifest are sufficient for benchmark reproduction; no live OONI query is performed.
The public fixture and license paths are recorded here, with their retained access date in `../external_resources.csv`; benchmark reproduction does not depend on refetching them.

Associated publication: Arturo Filastò and Jacob Appelbaum. *OONI: Open Observatory of Network Interference*. 2nd USENIX Workshop on Free and Open Communications on the Internet (FOCI 12), 2012.

The benchmark label is exact equality of the normalized input target recorded by the fixture. It is not a label for service ownership, common operator, legal entity, or equivalence across different URLs. Cross-target pairs are evaluated only against target identity. The frozen upstream test-fixture family is not a probability sample and pairs share observations; results are finite-family checks, not population estimates.

Source project: https://github.com/ooni/pipeline

Fixture directory: https://github.com/ooni/pipeline/tree/master/af/fastpath/fastpath/tests/data
