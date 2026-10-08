# CardiTherapy 0.2.0 CPU audit

## Scope and conclusion

CardiTherapy now executes reproducible, file-backed pacing-root experiments through the real CardiEP surface and native graph-Eikonal adapters. The validation supports software correctness and a narrow analytic activation-time calculation. It does **not** establish physiological pacing efficacy, patient personalization, uncertainty propagation, measured QRS duration, or clinical benefit. Other intervention classes remain schema contracts only.

Baseline revision: `5f359d9cf6d7befe4c1323b7e927ff8240044603`.
Pinned CardiEP revision: `2bcdd1ec2e282c1986d91459a0c39cea5b3ade15`.

Baseline: 10 tests passed; statement coverage 80.33%, combined statement/branch coverage 77.72%. The baseline suite primarily exercised a fake CardiEP delegate.
Repaired implementation: 82 tests passed with actual CardiEP installed; statement coverage 98.15%, combined statement/branch coverage 97.16%, branch coverage 94.44%.

## Verified repairs

| Gap | Resulting behavior |
|---|---|
| Wrong plan, missing/extra/duplicate outcomes accepted | Service requires exact subject/backend/plan and the complete arm-by-endpoint result set |
| Mutable request and conflicting lineage | Delegate receives a deep copy; complete original request and canonical hash retained; conflicting lineage rejected |
| NaN/Infinity, bool/string outcomes, invalid hashes and blank identifiers | Strict finite numeric, canonical JSON and hexadecimal hash checks |
| Duplicate endpoints and input artifact IDs | Rejected before execution |
| Misleading comparator or empty active pacing arm | Explicit empty comparators and one pacing intervention in active arms required |
| Invalid second arm could execute first arm before failure | All intervention contracts preflighted before simulation; deeper geometry/backend errors can still produce partial intermediate artifacts |
| Root selector conflicts, unsupported top-level settings or wrong delegate target | Fail closed rather than silently ignore intervention intent |
| Summary-only output bundle | Retains every returned activation/summary artifact and arm-to-output mapping |
| Missing hashes or reused/overwritten output files | Computes missing observed hashes; verifies inputs and outputs; checks conflicting artifact IDs and all final output hashes |
| Arbitrary summary values | Exactly one summary, numeric finite timing values and max-minus-min/span consistency required |
| Registered backend mistaken for executable backend | Doctor distinguishes names from current availability |
| Posterior reference implied uncertainty analysis | Explicit `uncertainty_propagated: false` and warning: lineage only |
| CLI supported only doctor | Adds version, request validation, execution and atomic result persistence; guards request/input/output artifact overwrites |
| Optional CardiEP installation undocumented/unpinned | Explicit commit-pinned `cardiep` extra; wheel includes type marker |

Backend names cannot be silently replaced; initialize a service with `register_defaults=False` to register a custom delegate under an existing name.

## Independent numerical verification

`python scripts/validate_cpu.py` executes the actual installed CardiEP API. It constructs synthetic right-triangle surface and unit-tetrahedron volumetric geometries. Every pair of vertices in these fixtures is linked by a mesh edge, so the independent reference is direct Euclidean distance divided by isotropic speed, without importing CardiEP's distance or propagation implementation.

Nine experiments cover three speeds (0.05, 0.1 and 0.2 cm/ms), surface coordinates in cm and mm, and native tetrahedral coordinates in cm. Each experiment runs twice and requires identical complete results. Control root 0 has activation span `1/speed`; root 1 has span `sqrt(2)/speed`. Thus the intervention increases span in these fixtures, and the audit retains that result rather than labeling it an improvement. Minimum activation time is zero. Maximum absolute errors and case outcomes appear in `validation/cpu/results.json`; tolerance is 1e-10 ms. These are analytic technical fixtures, not patients, disease models, or independent physiological measurements.

## Installation and execution

```bash
python -m pip install -e '.[dev,cardiep]'
pytest -q --cov=carditherapy --cov-branch --cov-fail-under=95
python scripts/validate_cpu.py
carditherapy doctor
carditherapy validate request.json
carditherapy run request.json --output result.json
```

The published CPU notebook installs both repositories from exact commits, creates fixtures from scratch, runs tests and analytic verification, and downloads a ZIP of logs/results. No GPU or user-supplied dataset is required for these checks. The notebook is a computational audit, not a clinical validation pipeline.

## Remaining scientific work

A twin-state reference is verified when local, but its contents do not parameterize CardiEP: anatomy and fixed EP parameters/settings are supplied separately. Non-local state references are lineage-only and explicitly warned as unverified. Posterior samples are not consumed. Activation span is a propagation observable, not a measured ECG QRS duration. These limitations prevent an efficacy, ranking, personalized response or calibrated uncertainty claim.

A meaningful empirical pacing benchmark requires matched anatomy, coordinates/units, documented baseline and paced stimulation locations/timing, measured activation maps for both conditions, subject-level grouping, and held-out subjects/conditions. Calibration must use baseline data only; pacing-response outcomes must remain held out. ECG alone cannot directly validate an activation-span endpoint. Missing mapping, stimulation metadata or compatible observations must block the empirical benchmark, not be filled with guessed labels. No such paired patient dataset was run in this audit.

Verification and physiological validation have different purposes. Galappaththige et al. distinguish code/calculation verification, real-world validation and input uncertainty in patient-specific cardiac models, including variation across patients: https://doi.org/10.1371/journal.pcbi.1010541. The FDA credibility guidance similarly ties evidence to a defined context of use: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/assessing-credibility-computational-modeling-and-simulation-medical-device-submissions. These references inform the audit boundary; they are not validation evidence for CardiTherapy.
