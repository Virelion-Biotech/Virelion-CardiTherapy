# Executable intervention models in 0.3.0

CardiTherapy now has three executable scientific paths. They are independent,
restricted research models with numerical evidence, not equivalent validated
representations of every intervention class or patient outcome.

## Common execution and evidence contracts

New backends require one local baseline model artifact with explicit matching
`subject_id`, a local JSON twin-state reference, exactly one empty comparator,
and one intervention in each active arm. State bytes are verified for lineage;
model parameters come from the baseline artifact, not unconsumed twin-state
fields. Input SHA-256 and subject are checked, all arms are preflighted, numerical
arms finish before publication, and input bytes are rechecked before writing.
A unique output directory beneath `settings.output_dir` isolates concurrent runs.
Each arm has a hashed trace; the result retains the full request and its hash.
Raw signed comparator differences do not express efficacy or a treatment ranking.

All built-in outcomes have `endpoint_scope: model_proxy`. A `patient_outcome`
claim without empirical result status fails at the service boundary. Third-party
empirical claims remain the backend author's responsibility to substantiate.
New backends reject `posterior_ref`; uncertainty is not propagated. Pacing keeps
its existing lineage-only posterior behavior with a warning. No interval coverage,
clinical calibration or patient response evidence is implied by deterministic QC.

## Prescribed-lesion graph ablation

Backend: `graph-ablation-v1`; baseline kind: `therapy_conduction_graph`.
JSON requires exactly `subject_id`, `nodes_mm` (unique 3D coordinates), `edges`
(undirected `[node_a,node_b,travel_time_ms]`, positive finite weights) and `roots`
(`[{'node': index, 'time_ms': nonnegative_delay}]`). Node/edge limits are 10,000
and 100,000. Graph weights are supplied explicitly; geometry alone does not
produce a calibrated myocardial conduction model. Graph may contain disconnected
components; their viable reachability is reported rather than silently excluded.

An `ablation` intervention targeting `conduction_graph` requires either
`lesion_nodes: [indices]` or `center_mm: [x,y,z], radius_mm: r`. A sphere selects
nodes by Euclidean distance. Selected nodes and incident edges are nonconducting.
Activation roots cannot be removed. Shortest-path propagation returns the earliest
reachable activation from scheduled roots. It does not model refractoriness,
reexcitation, source-sink effects, wavefront curvature, lesion transmurality,
thermal dose, lesion healing, VT induction/termination or target selection.

| Endpoint | Definition |
|---|---|
| `lesion_node_fraction` | Removed node count / all node count; not tissue volume or mass |
| `viable_reached_fraction` | Reachable nonlesion nodes / all nonlesion nodes |
| `unreachable_viable_nodes` | Count of nonlesion nodes not reachable from scheduled roots |
| `activation_span_reachable_ms` | Max minus min activation among reached viable nodes |

Arrival times are JSON `null` for removed or unreached nodes; masks distinguish
them. A smaller reachable activation span can arise from tissue disconnection;
it cannot independently indicate improved activation. All four endpoints and
masks should be inspected together.

Ablation/activation graph research motivates this restricted topology experiment,
but it does not reproduce VITA or reaction-Eikonal VT induction:
[Campos et al., automated scar-related VT induction/treatment](https://pmc.ncbi.nlm.nih.gov/articles/PMC10114098/).
Numerical verification uses independent Floyd-Warshall matrices, delayed roots,
disconnection, alternate-path detours, spherical masks and invalid-root rejection.

## IV pharmacokinetics and channel block

Backend: `iv-pkpd-v1`; baseline kind: `therapy_pkpd_model`. JSON requires
`subject_id`, `volume_L`, `clearance_L_h`, `molecular_weight_g_mol`,
`unbound_fraction` (0..1), `parameter_source`, and `channels` with each channel's
`ic50_uM`, `hill` and nonblank `source`. Optional `effect_rate_h_inv` is positive.
All dose-response and PK coefficients are supplied explicitly; synthetic examples
are labeled synthetic. A source string alone does not establish a measured or
valid patient model. Units are encoded in field names and never inferred.

A `pharmacologic` intervention targeting `iv_bolus` accepts only
`doses: [{'time_h': t, 'amount_mg': D}]` with positive amounts and nonnegative
times within the sample horizon. Repeated/simultaneous boluses superpose.
There is no oral absorption, infusion, nonlinear elimination, metabolite,
drug interaction or multi-compartment distribution model.

With k=CL/V, plasma concentration is the sum of (D/V) exp[-k(t-t_d)] after
each dose. Unbound micromolar concentration is plasma mg/L multiplied by
1000 f_u / molecular weight g/mol. Exact AUC over the horizon is the sum of
(D/CL)(1-exp[-k(T-t_d)]). Remaining and eliminated amounts sum to administered
mass; the solver checks the mass balance. All doses are included in the grid,
so plasma Cmax is exact for this bolus-only model. Samples at doses use the
right-hand concentration limit, including boluses at the final horizon.

If supplied, the effect compartment solves dCe/dt=k0(Cu-Ce), initially zero.
The analytic convolution handles equal/near-equal k0 and k stably. Without it,
Ce=Cu instantaneously. Static channel block is Ce^h/(IC50^h+Ce^h), evaluated
in a stable log-domain form. It approximates static pore inhibition and omits
state-dependent binding and use dependence. No underlying ionic-current model
is solved, so no APD, QT, torsades, therapeutic benefit or outcome is inferred.
See primary [cardiac drug exposure/block modeling](https://pmc.ncbi.nlm.nih.gov/articles/PMC6483901/)
and [channel interaction parameterization](https://pmc.ncbi.nlm.nih.gov/articles/PMC4786197/).

Settings are `output_dir` and strictly increasing `sample_times_h` beginning at
zero, with 2..10,000 entries. Every bolus event is added. Endpoints are
`plasma_cmax_mg_L`, `plasma_auc_mg_h_L`, `unbound_cmax_uM`,
`terminal_amount_mg`, `eliminated_amount_mg` and
`sampled_peak_block_<channel>` (fraction 0..1). Effect-site block maxima are
sampled and require time-grid refinement; they are not analytic global maxima.
The trace preserves plasma, unbound and effect-site concentrations, block by
channel, dosing events, model parameters and mass balance.

## Verification and remaining validation

`validation/cpu/interventions.json` records independent shortest-path and
adaptive-ODE checks, separate Hill algebra, delayed effect-site sampling
refinement, runtime versions and source hashes. SciPy is only needed for this
independent harness (`[validation]`), not for either new scientific backend.
The existing nine CardiEP pacing checks remain separate in `results.json`.
Successful runs report `software_checked`: independent numerical cases do not
establish empirical accuracy across patients, geometry or drugs.

For empirical ablation validation, use registered baseline/post-lesion conduction
maps with documented stimulation sites/timing and measured lesion geometry,
holding response measurements out of calibration. Thermal lesion prediction
requires a separate bioheat/injury model and its data. VT outcomes require an
appropriate reentrant EP model and independent endpoint measurements.

For pharmacology, validate exposure against time-stamped dose/concentration
measurements with units and binding assay provenance, and channel inhibition
against independent concentration-response assays. Patient grouping, drug/assay
protocol, missingness and held-out splits must be resolved. Plasma concentration
and static IC50 data alone cannot validate a clinical benefit or arrhythmia
probability. No measured patient treatment dataset was used in this release.

Device efficacy, regenerative therapy and surgery remain contract-only and fail
closed. Implementing their equations, coupling and empirical validation requires
separate context-specific work; they are not interchangeable parameter tweaks.


Local release evidence: 194 tests passed with the pinned CardiEP source installed,
98.33% combined statement/branch coverage. Core-wheel checks run without CardiEP,
NumPy or SciPy; 191 tests pass and optional integration checks skip. Both new
CLI examples run from that core wheel. Source/wheel builds and Ruff checks pass.
These are local CPU results; no hosted CI pass is implied.
