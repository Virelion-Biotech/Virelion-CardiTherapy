# Regenerative, genetic and vascular intervention contracts v1

CardiTherapy now represents six intervention modalities without registering an execution backend: AAV gene delivery, circular RNA, modified mRNA, RNA interference, cell-derived products/extracellular vesicles, and tissue-engineered vascular grafts.

## Required evidence and model boundary

Every spec requires target/mechanism, dose/unit/route, source maturity, source record IDs and source provenance (including SHA-256), comparator definition, uncertainty reference, calibration status/evidence, declared model limitations. A source hash is integrity metadata, not proof of publisher authenticity or efficacy.

Modality-specific fields are required:
- AAV: capsid, promoter, payload, biodistribution and immunogenicity.
- circRNA/modified mRNA: payload, transient expression window and tissue targeting.
- RNA interference: target transcript/protein, chemistry and pharmacodynamic readouts.
- Cell-derived products: cell source, product identity, manufacturing, potency and proposed mechanism.
- Vascular graft: material, product identity, manufacturing, potency and patency outcomes.

Vascular grafts are represented as a separate `surgical` intervention in the `vascular_surgical` domain. Graft patency is not a myocardial regeneration endpoint.

## Endpoint separation

The output contract distinguishes target engagement, expression, biodistribution, ventricular function, fibrosis, cardiomyocyte proliferation, cytokinesis, cardiomyocyte number, arrhythmia and toxicity. A simulated LVEF change is a ventricular-function model proxy; it cannot be re-labelled as new myocardium or clinical benefit. Patient outcomes still require empirical validation in the service boundary.

Model-supported endpoints are empty by default. Declaring any model-supported endpoint requires a non-empty calibration evidence record and a calibration status other than `none`. No company-reported effect size is translated into model parameters by this contract.

## Execution remains fail-closed

No regenerative or vascular backend is registered by default. The existing `CardiTherapyService` only executes explicitly registered backends; a regenerative request without a registered backend continues to raise `BackendUnavailable`. These specs are descriptive contracts, not a therapy selector, recommendation engine or simulation of treatment efficacy.
