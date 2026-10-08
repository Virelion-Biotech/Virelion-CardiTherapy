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

CardiTherapy is **not** a clinical treatment recommender. It does not select therapy for a patient and does not fabricate efficacy when no validated backend exists. The built-in backends execute restricted pacing, prescribed-lesion ablation and IV pharmacology experiments. Their endpoints are explicitly labeled model proxies; none is a patient outcome model.

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
outputs, not clinical outcomes. The additional ablation and pharmacology backends below have separate model and
endpoint contracts. Device efficacy, regenerative, surgical and patient-benefit
endpoints continue to fail closed.

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
clinical benefit. The 0.2.0 notebook covers pacing only. Version 0.3.0 adds restricted ablation
and pharmacology experiments; other therapy types remain contract-only.


## Additional executable models (0.3.0)

| Backend | Implemented model | Supported endpoints | Scientific limit |
|---|---|---|---|
| `cardiep-pacing-v1` | CardiEP activation-root perturbation | Activation min/max/span | No measured QRS or patient benefit |
| `graph-ablation-v1` | Prescribed binary nonconducting lesion on a weighted graph | Lesion node fraction, viable tissue reachability, disconnected nodes, reachable activation span | No thermal lesion formation, reentry or arrhythmia termination |
| `iv-pkpd-v1` | Exact one-compartment repeated IV bolus exposure, optional effect compartment, Hill channel inhibition | Peak exposure, exact AUC, remaining/eliminated amount, sampled peak channel block | No action potential, QT, efficacy or dosing recommendation |

Both new backends run with the core installation on CPU. Run examples from the
repository root:

```bash
carditherapy run examples/ablation_request.json --output /tmp/ablation.json
carditherapy run examples/pharmacology_request.json --output /tmp/pharmacology.json
python -m pip install -e '.[dev,validation,cardiep]'
python scripts/validate_interventions.py
```

Examples use synthetic parameters and geometry. Outputs retain SHA-256 traces,
comparator differences, `endpoint_scope: "model_proxy"`, endpoint domain and
`patient_validated: false`. Doctor exposes each backend's capabilities and limits.
New backends reject posterior references because they do not propagate posterior
uncertainty. Regenerative, surgical, device efficacy and clinical patient outcome
models remain unimplemented. These gaps cannot be resolved by assigning benefit
to model proxies.

Independent verification compares lesion propagation with Floyd-Warshall, PK and
effect-site concentrations/AUC with adaptive ODE integration, and channel block
with separate algebra. The committed [numerical report](validation/cpu/interventions.json)
records model and source provenance and sampling refinement. This is numerical
verification, not measured treatment-response validation.

See [model contracts and equations](docs/INTERVENTION_MODELS.md) for assumptions,
units, endpoint definitions and the empirical evidence still needed.
