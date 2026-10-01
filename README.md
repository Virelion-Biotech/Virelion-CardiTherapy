# Virelion-CardiTherapy

Virtual-intervention layer for the Virelion HeartTwin stack.

CardiTherapy defines contracts for reproducible in-silico intervention experiments on an already specified cardiac twin. It supports explicit intervention plans, comparator arms, intervention-specific backend adapters, outcome artifacts, uncertainty references, and provenance.

## Scope

CardiTherapy owns:
- typed virtual interventions and intervention plans;
- pacing, ablation, pharmacologic, device, regenerative and surgical experiment contracts;
- comparator/control definitions;
- execution through registered intervention backends;
- outcome bundles and derived endpoint references;
- uncertainty links back to CardiInfer;
- reproducible intervention manifests and provenance.

CardiTherapy is **not** a clinical treatment recommender. It does not select therapy for a patient and does not fabricate efficacy when no validated backend exists.

## Quick start

```bash
python -m pip install -e '.[dev]'
pytest -q
carditherapy doctor
```

## Scientific boundary

A virtual intervention result is a model-dependent simulation. It is not evidence that a real patient will benefit, nor is it a clinical recommendation.

## License

AGPL-3.0-or-later.
