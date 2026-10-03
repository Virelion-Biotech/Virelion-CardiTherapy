# HeartTwin integration

Initial capabilities:

- `therapy.health`
- `therapy.run`

CardiTherapy should be called only after HeartTwin has an explicit twin state and, where available, a CardiInfer posterior or uncertainty artifact.

## Proposed registry entry

```yaml
- name: CardiTherapy
  repository: Virelion-Biotech/Virelion-CardiTherapy
  capabilities: [therapy.health, therapy.run]
  builtin: carditherapy
  endpoint: ${CARDITHERAPY_URL}
```

HeartTwin should retain the complete intervention plan, comparator definitions, backend identities, model-state references, posterior reference, outcome artifacts, validation status, and provenance.

CardiTherapy is an in-silico experiment engine. HeartTwin must not present a simulated arm comparison as a treatment recommendation or predicted clinical benefit without appropriate independent evidence.
