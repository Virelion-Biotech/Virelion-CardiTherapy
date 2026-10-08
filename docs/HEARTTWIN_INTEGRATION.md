# HeartTwin integration

Capabilities:

- `therapy.health`
- `therapy.run`

CardiTherapy is called only after HeartTwin has an explicit canonical twin state and, where available, a CardiInfer posterior or uncertainty artifact. The service now records the exact twin-state artifact ID/SHA-256, posterior artifact ID/SHA-256, and baseline artifact IDs in result provenance so intervention runs cannot silently detach from the state they were meant to test.

## Registry entry

```yaml
- name: CardiTherapy
  repository: Virelion-Biotech/Virelion-CardiTherapy
  capabilities: [therapy.health, therapy.run]
  builtin: carditherapy
  endpoint: ${CARDITHERAPY_URL}
```

HeartTwin retains the complete intervention plan, comparator definitions, backend identities, model-state references, posterior reference, outcome artifacts, validation status, and provenance as a typed therapy artifact.

CardiTherapy is an in-silico experiment engine. HeartTwin must not present a simulated arm comparison as a treatment recommendation or predicted clinical benefit without appropriate independent evidence.

## Execution boundary in 0.2.0

Every returned result must match the plan ID and complete arm/endpoint matrix.
Request identity is recorded as `therapy_request_sha256`, accompanied by the
complete request snapshot. This hash includes file URIs and output directories;
it identifies an exact request, not a path-independent biological experiment.

The pacing adapter preserves all CardiEP outputs, actual arm settings and hashes.
Anatomy inputs and fixed EP parameters drive the calculation. State/posterior
references provide lineage; posterior uncertainty is explicitly not propagated.
`software_checked` describes the orchestration level even if a delegate reports
a higher status. No automatic treatment ranking or clinical outcome is emitted.


## Numerical intervention models in 0.3.0

`therapy.health.backend_details` reports supported intervention kinds, endpoint
names, required baseline model and `patient_validated: false` for each built-in
backend. All built-in outcomes declare `endpoint_scope: model_proxy`.
`graph-ablation-v1` and `iv-pkpd-v1` consume explicit local baseline model artifacts
and reject posterior references. They require one empty comparator and one
intervention per active arm, preflight all arms, and write isolated immutable
run traces after numerical completion. Comparator differences are signed raw
endpoint changes, not treatment rankings or efficacy estimates.

Ablation traces report unreached viable nodes separately from ablated nodes.
Consumers must not interpret a shorter activation span among remaining reached
nodes as improved global activation. PK channel-block peaks are sampled when an
effect compartment is enabled; sample-grid refinement is required. No patient
outcome or probability of clinical benefit is generated.
