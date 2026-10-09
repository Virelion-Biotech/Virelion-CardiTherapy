# Scientific audit changes — 2026-10-09

## Behavior

Add explicit endpoint-tier metadata and tag built-in pacing/graph-ablation outputs as electrical; pharmacology reference outputs stay proxy tier.

## Scope and remaining evidence

Tier metadata is descriptive. It is not a cumulative endpoint evidence gate. Existing patient-outcome validation-status checks are not independently authenticated. Coupled mechanics, lead-position/delay models and longitudinal validation remain unresolved.

## Implementation

- `src/carditherapy/models.py`
- `src/carditherapy/pacing_backend.py`
- `src/carditherapy/research.py`
- `tests/test_pacing_backend.py`

## Verification

Regression tests accompany the changes. Repository test results are recorded in the audit completion report and draft pull request. Software regression checks do not establish numerical, biological, transport or clinical validity.
