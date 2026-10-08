# CardiTherapy architecture

CardiTherapy is the downstream virtual-intervention layer of HeartTwin.

```text
personalized HeartTwin state
        |
        +---- CardiInfer posterior / uncertainty
        |
        v
 explicit InterventionPlan
 control + virtual intervention arms
        |
 registered therapy backend(s)
        |
 EP / mechanics / flow / phenotype simulations
        |
 comparable endpoint outcomes
        |
 uncertainty + provenance
        |
 CardiEval / HeartTwin
```

## Responsibility boundary

CardiTherapy owns experiment definition, intervention-arm orchestration, and typed intervention outcomes. It delegates spatial electrophysiology, mechanics, flow and molecular forward equations. Version 0.3.0 also owns restricted weighted-graph lesion and one-compartment PK/Hill experiment backends, with explicit model-proxy endpoints.

Those remain in CardiEP, CardiMech, CardiFlow, CardiSim, or future specialist backends. CardiInfer owns posterior inference and uncertainty propagation. CardiEval should own independent evaluation.

## Intervention classes

The contract supports pacing, ablation, pharmacologic, device, regenerative, surgical, and custom virtual interventions. Support in the schema does not imply that a scientifically validated backend exists for every intervention class.

## Validation ladder

1. Contract/software checks.
2. Deterministic intervention reproducibility.
3. Numerical backend validation.
4. Synthetic counterfactual checks.
5. Retrospective held-out outcome comparison.
6. External prospective validation where appropriate.

CardiTherapy must not transform model outputs into clinical recommendations.

All built-in endpoints have `endpoint_scope: model_proxy`. The service rejects
`patient_outcome` results lacking `empirically_checked` status. That status must
be backed by appropriate independent evidence from any external backend; merely
setting a label does not establish validity.
