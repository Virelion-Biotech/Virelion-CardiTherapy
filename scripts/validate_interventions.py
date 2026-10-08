"""Independent shortest-path and ODE checks, not empirical therapy validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from itertools import pairwise
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import solve_ivp
from scipy.sparse.csgraph import floyd_warshall

from carditherapy.ablation_backend import propagate, validate_graph
from carditherapy.pharmacology_backend import simulate_pk
from carditherapy.serialization import write_json


def verify():
    generator = np.random.default_rng(2718)
    graphs = []
    for count in [6, 12, 30]:
        edges = [
            [i, j, float(generator.uniform(0.1, 10))]
            for i in range(count)
            for j in range(i + 1, count)
            if generator.random() < 0.3 or j == i + 1
        ]
        roots = [{"node": 0, "time_ms": 0}, {"node": count - 1, "time_ms": 3}]
        model = {
            "subject_id": "synthetic",
            "nodes_mm": [[i, 0, 0] for i in range(count)],
            "edges": edges,
            "roots": roots,
        }
        for removed in [set(), set(range(2, count - 1, 3))]:
            _, trace = propagate(validate_graph(model), roots, removed)
            matrix = np.full((count, count), math.inf)
            np.fill_diagonal(matrix, 0)
            for a, b, cost in edges:
                if a not in removed and b not in removed:
                    matrix[a, b] = matrix[b, a] = cost
            distances = floyd_warshall(matrix, directed=False)
            expected = np.minimum(distances[0], 3 + distances[count - 1])
            actual = np.array([math.inf if v is None else v for v in trace["activation_ms"]])
            viable = np.array([i not in removed for i in range(count)])
            match = bool(np.array_equal(np.isfinite(actual[viable]), np.isfinite(expected[viable])))
            finite = viable & np.isfinite(expected)
            error = float(np.max(abs(expected[finite] - actual[finite])))
            graphs.append(
                {
                    "nodes": count,
                    "lesion_nodes": len(removed),
                    "maximum_error_ms": error,
                    "reachability_matches": match,
                    "passed": match and error < 1e-10,
                }
            )
    pk_checks = []
    doses = [(0.0, 10.0), (1.3, 5.0), (3.7, 20.0)]
    horizon = 8.0
    for k0 in [None, 0.1, 0.2, 0.20000000000001, 0.5]:
        model = {
            "subject_id": "synthetic",
            "volume_L": 10.0,
            "clearance_L_h": 2.0,
            "molecular_weight_g_mol": 500.0,
            "unbound_fraction": 0.5,
            "parameter_source": "synthetic ODE verification",
            "channels": {
                "IKr": {"ic50_uM": 1.0, "hill": 1.5, "source": "synthetic ODE verification"}
            },
        }
        if k0 is not None:
            model["effect_rate_h_inv"] = k0
        times = np.linspace(0, horizon, 161).tolist()
        metrics, trace = simulate_pk(model, doses, times)
        grid = trace["time_h"]
        state = np.zeros(3)
        samples = {}
        start = 0
        k = 0.2
        conversion = 1.0

        def rhs(_, state, k0=k0, k=k, conversion=conversion):
            plasma, effect, _ = state
            return [-k * plasma, 0 if k0 is None else k0 * (conversion * plasma - effect), plasma]

        for event, (time, amount) in enumerate(doses):
            if event:
                solve = solve_ivp(
                    rhs,
                    [start, time],
                    state,
                    rtol=1e-11,
                    atol=1e-13,
                    dense_output=True,
                    max_step=0.05,
                )
                if not solve.success:
                    raise RuntimeError(solve.message)
                for sample in grid:
                    if start < sample < time:
                        samples[sample] = solve.sol(sample)
                state = solve.y[:, -1]
            state[0] += amount / model["volume_L"]
            samples[time] = state.copy()
            start = time
        solve = solve_ivp(
            rhs, [start, horizon], state, rtol=1e-11, atol=1e-13, dense_output=True, max_step=0.05
        )
        if not solve.success:
            raise RuntimeError(solve.message)
        for sample in grid:
            if sample > start:
                samples[sample] = solve.sol(sample)
        plasma = np.array([samples[t][0] for t in grid])
        effect = plasma * conversion if k0 is None else np.array([samples[t][1] for t in grid])
        concentration_error = float(np.max(abs(plasma - np.array(trace["plasma_mg_L"]))))
        effect_error = float(np.max(abs(effect - np.array(trace["effect_site_uM"]))))
        auc_error = abs(float(solve.y[2, -1]) - metrics["plasma_auc_mg_h_L"])
        # Independent direct algebra, moderate concentrations; no shared Hill helper.
        expected_block = effect**1.5 / (1 + effect**1.5)
        block_error = float(np.max(abs(expected_block - np.array(trace["channel_block"]["IKr"]))))
        pk_checks.append(
            {
                "effect_rate_h_inv": k0,
                "maximum_plasma_error_mg_L": concentration_error,
                "maximum_effect_site_error_uM": effect_error,
                "auc_error_mg_h_L": auc_error,
                "maximum_hill_block_error": block_error,
                "mass_balance_residual_mg": trace["mass_balance_residual_mg"],
                "passed": max(concentration_error, effect_error, auc_error, block_error) < 1e-8,
            }
        )
    refinement = []
    model["effect_rate_h_inv"] = 0.5
    # Independent single-bolus effect-site maximum at log(k0/k)/(k0-k).
    peak_time = math.log(0.5 / 0.2) / (0.5 - 0.2)
    peak_effect = 0.5 / (0.5 - 0.2) * (math.exp(-0.2 * peak_time) - math.exp(-0.5 * peak_time))
    exact_block = peak_effect**1.5 / (1 + peak_effect**1.5)
    for spacing in [2.0, 1.0, 0.1]:
        metrics, _ = simulate_pk(model, [(0, 10)], np.arange(0, 8 + spacing / 2, spacing).tolist())
        error = abs(metrics["sampled_peak_block_IKr"] - exact_block)
        refinement.append({"sample_spacing_h": spacing, "peak_block_absolute_error": error})
    refinement_passed = (
        all(
            b["peak_block_absolute_error"] < a["peak_block_absolute_error"]
            for a, b in pairwise(refinement)
        )
        and refinement[-1]["peak_block_absolute_error"] < 1e-4
    )
    return {
        "schema_version": "carditherapy-intervention-verification-v1",
        "computational_status": "passed"
        if all(v["passed"] for v in graphs + pk_checks) and refinement_passed
        else "failed",
        "graph_reference": "SciPy Floyd-Warshall on independently constructed lesion-masked matrices",
        "pharmacology_reference": "SciPy adaptive ODE plasma/effect/AUC with explicit bolus jumps; independent Hill algebra",
        "graph_checks": graphs,
        "pharmacology_checks": pk_checks,
        "sampling_refinement": refinement,
        "sampling_refinement_passed": refinement_passed,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
        },
        "empirical_status": "not_validated",
        "limitations": [
            "Synthetic model parameters only; no patient responses tested.",
            "Graph lesion fraction counts nodes, not tissue volume; no thermal formation or reentry.",
            "Channel block is static pore inhibition, not ionic dynamics or clinical efficacy.",
            "Effect-site peak remains sample-grid dependent.",
            "No regenerative, surgical or device efficacy model supplied.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("validation/cpu/interventions.json"))
    args = parser.parse_args()
    report = verify()
    root = Path(__file__).resolve().parents[1]
    report["source_sha256"] = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "src/carditherapy").glob("*.py"))
    }
    report["source_sha256"]["scripts/validate_interventions.py"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    write_json(args.output, report)
    print(json.dumps(report, indent=2))
    return 0 if report["computational_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
