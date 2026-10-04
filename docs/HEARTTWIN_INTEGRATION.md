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
