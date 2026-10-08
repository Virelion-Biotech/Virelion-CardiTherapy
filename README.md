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

CardiTherapy is **not** a clinical treatment recommender. It does not select therapy for a patient and does not fabricate efficacy when no validated backend exists. The built-in `cardiep-pacing-v1` backend is deliberately narrow: it delegates pacing-root changes to CardiEP and reports activation-timing endpoints only.

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


## Built-in pacing backend

`cardiep-pacing-v1` provides a real but deliberately narrow intervention path.
It requires one EP anatomy artifact in `baseline_refs`, an explicit CardiEP
backend and parameter set in request settings, and either a comparator arm or
one pacing intervention per active arm. Pacing interventions may modify only
activation-root settings such as `root_node`, `root_nodes`, and
`root_activation_ms`.

The only supported endpoints are `activation_span_ms`,
`activation_min_ms`, and `activation_max_ms`. These are EP simulation
outputs, not clinical outcomes. Ablation, pharmacologic, device efficacy,
regenerative, surgical, and patient-benefit endpoints continue to fail closed.

## CPU-verified release 0.2.0

Install the executable pacing integration with a pinned CardiEP dependency:

```bash
python -m pip install -e '.[dev,cardiep]'
pytest -q
python scripts/validate_cpu.py
carditherapy --version
carditherapy validate request.json
carditherapy run request.json --output result.json
```

`doctor` reports both registered backends and their actual availability. Requests
and results use strict finite JSON contracts. A successful run must return every
requested arm/endpoint exactly once, preserve subject/backend/plan lineage, and
retain verified output artifacts. Results include the complete request and its
hash. Reusing a backend name requires an explicitly configured service without
default registration.

For pacing, comparators must be empty and each active arm must have one pacing
intervention. Root selectors must be unambiguous. Unsupported request settings,
intervention targets and endpoints fail closed. Anatomy and fixed EP parameters
are supplied separately: twin-state contents and posterior samples do not
parameterize this backend or propagate uncertainty.

[CPU audit](docs/CPU_AUDIT.md) · [Analytic results](validation/cpu/results.json) ·
[From-scratch CPU notebook](notebooks/CardiTherapy_CPU_Validation.ipynb)

The nine analytic experiments validate technical activation-time calculations
and reproducibility. No measured patient pacing responses were tested. Activation
span is not measured ECG QRS duration, and simulated changes do not establish
clinical benefit. Other therapy types remain contract-only.
