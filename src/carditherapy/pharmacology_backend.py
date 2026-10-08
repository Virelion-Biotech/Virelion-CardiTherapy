"""Exact one-compartment IV-bolus PK, optional effect site, and static Hill block.

Parameters must be supplied explicitly with provenance. This is not an ionic
cell/tissue simulation, QT-risk model, therapeutic efficacy or dosing recommender.
"""

from __future__ import annotations

import math
from itertools import pairwise

from .models import InterventionRunRequest
from .research import finish, number, prepare

BASE_UNITS = {
    "plasma_cmax_mg_L": "mg/L",
    "plasma_auc_mg_h_L": "mg*h/L",
    "unbound_cmax_uM": "uM",
    "terminal_amount_mg": "mg",
    "eliminated_amount_mg": "mg",
}


def validate_model(data):
    required = {
        "subject_id",
        "volume_L",
        "clearance_L_h",
        "molecular_weight_g_mol",
        "unbound_fraction",
        "channels",
        "parameter_source",
    }
    if set(data) - required - {"effect_rate_h_inv"} or not required <= set(data):
        raise ValueError(
            "PK model requires explicit compartment, binding, channels and parameter_source"
        )
    for key in ["volume_L", "clearance_L_h", "molecular_weight_g_mol"]:
        number(data[key], key, positive=True)
    if number(data["unbound_fraction"], "unbound fraction") > 1:
        raise ValueError("Unbound fraction must be <=1")
    if not isinstance(data["parameter_source"], str) or not data["parameter_source"].strip():
        raise ValueError("PK model requires parameter_source")
    if "effect_rate_h_inv" in data:
        number(data["effect_rate_h_inv"], "effect rate", positive=True)
    channels = data["channels"]
    if not isinstance(channels, dict) or not 1 <= len(channels) <= 32:
        raise ValueError("Provide 1..32 measured channel dose-response parameter sets")
    for channel, parameters in channels.items():
        if (
            not channel
            or not channel.replace("_", "").isalnum()
            or not isinstance(parameters, dict)
            or set(parameters) != {"ic50_uM", "hill", "source"}
        ):
            raise ValueError("Channels require named ic50_uM/hill/source parameter sets")
        number(parameters["ic50_uM"], "IC50", positive=True)
        number(parameters["hill"], "Hill coefficient", positive=True)
        if not isinstance(parameters["source"], str) or not parameters["source"].strip():
            raise ValueError("Channel parameters require source")
    rate = data["clearance_L_h"] / data["volume_L"]
    conversion = 1000 * data["unbound_fraction"] / data["molecular_weight_g_mol"]
    if not math.isfinite(rate) or rate <= 0 or not math.isfinite(conversion):
        raise ValueError("PK parameter ratios overflow")


def dose_schedule(intervention, horizon):
    if (
        intervention.kind != "pharmacologic"
        or intervention.target != "iv_bolus"
        or intervention.model_service not in {None, "CardiTherapy"}
        or intervention.model_capability not in {None, "therapy.run"}
    ):
        raise ValueError("PK interventions must be pharmacologic with iv_bolus target")
    if set(intervention.parameters) != {"doses"}:
        raise ValueError("IV bolus intervention requires doses only")
    doses = intervention.parameters["doses"]
    if not isinstance(doses, list) or not 1 <= len(doses) <= 1000:
        raise ValueError("Provide 1..1000 IV boluses")
    normalized = []
    for dose in doses:
        if not isinstance(dose, dict) or set(dose) != {"time_h", "amount_mg"}:
            raise ValueError("Doses require time_h/amount_mg")
        time = number(dose["time_h"], "dose time")
        amount = number(dose["amount_mg"], "dose amount", positive=True)
        if time > horizon:
            raise ValueError("Dose lies beyond sample horizon")
        normalized.append((time, amount))
    return sorted(normalized)


def concentration(model, doses, time):
    k = model["clearance_L_h"] / model["volume_L"]
    scale = 1000 * model["unbound_fraction"] / model["molecular_weight_g_mol"]
    plasma = 0.0
    effect = 0.0
    k0 = model.get("effect_rate_h_inv")
    for dose_time, amount in doses:
        elapsed = time - dose_time
        if elapsed < 0:
            continue
        initial = amount / model["volume_L"]
        decay = math.exp(-k * elapsed)
        plasma += initial * decay
        if k0 is not None:
            difference = k0 - k
            # Stable convolution: k0*(exp(-k*t)-exp(-k0*t))/(k0-k).
            if difference == 0:
                response = k0 * elapsed * decay
            elif difference > 0:
                response = k0 * decay * (-math.expm1(-difference * elapsed)) / difference
            else:
                response = (
                    k0 * math.exp(-k0 * elapsed) * math.expm1(difference * elapsed) / difference
                )
            effect += initial * scale * response
    unbound = plasma * scale
    if k0 is None:
        effect = unbound
    if not all(math.isfinite(v) for v in (plasma, unbound, effect)):
        raise ValueError("PK concentrations overflow")
    return plasma, unbound, effect


def hill_block(concentration_uM, ic50, hill):
    if concentration_uM == 0:
        return 0.0
    exponent = hill * (math.log(ic50) - math.log(concentration_uM))
    if exponent >= 0:
        inverse = math.exp(-exponent)
        return inverse / (1 + inverse)
    return 1 / (1 + math.exp(exponent))


def simulate_pk(model, doses, times):
    k = model["clearance_L_h"] / model["volume_L"]
    horizon = times[-1]
    # Include all discontinuity events: concentrations are right-continuous.
    grid = sorted(set(times) | {t for t, _ in doses})
    trace = [concentration(model, doses, time) for time in grid]
    auc = sum(
        amount / model["clearance_L_h"] * (-math.expm1(-k * (horizon - time)))
        for time, amount in doses
    )
    terminal = sum(amount * math.exp(-k * (horizon - time)) for time, amount in doses)
    eliminated = sum(amount * (-math.expm1(-k * (horizon - time))) for time, amount in doses)
    metrics = {
        "plasma_cmax_mg_L": max(row[0] for row in trace),
        "unbound_cmax_uM": max(row[1] for row in trace),
        "plasma_auc_mg_h_L": auc,
        "terminal_amount_mg": terminal,
        "eliminated_amount_mg": eliminated,
    }
    blocks = {
        channel: [hill_block(row[2], p["ic50_uM"], p["hill"]) for row in trace]
        for channel, p in model["channels"].items()
    }
    metrics.update(
        {f"sampled_peak_block_{channel}": max(values) for channel, values in blocks.items()}
    )
    administered = sum(amount for _, amount in doses)
    if not all(math.isfinite(value) for value in metrics.values()) or not math.isfinite(
        administered
    ):
        raise ValueError("Nonfinite PK metrics")
    balance = abs(administered - terminal - eliminated)
    if balance > 1e-10 * max(1, administered):
        raise ValueError("PK mass conservation failed")
    return metrics, {
        "time_h": grid,
        "plasma_mg_L": [v[0] for v in trace],
        "unbound_uM": [v[1] for v in trace],
        "effect_site_uM": [v[2] for v in trace],
        "channel_block": blocks,
        "metrics": metrics,
        "mass_balance_residual_mg": balance,
        "doses": [{"time_h": t, "amount_mg": a} for t, a in doses],
        "parameters": model,
        "sampling": "Right-continuous at dose events; effect-site block peak is sampled, not an analytic global maximum.",
    }


class PharmacologyBackend:
    name = "iv-pkpd-v1"

    def describe(self):
        return {
            "name": self.name,
            "intervention_kinds": ["pharmacologic"],
            "endpoints": [*BASE_UNITS, "sampled_peak_block_<channel>"],
            "endpoint_scope": "model_proxy",
            "requires": "therapy_pkpd_model",
            "patient_validated": False,
            "model": "IV bolus one-compartment PK / static Hill channel block",
        }

    def available(self):
        return True

    def run(self, request):
        request = InterventionRunRequest.model_validate(request.model_dump())
        if len(request.baseline_refs) != 1:
            raise ValueError("Exactly one PK model baseline is required")
        # Endpoint names depend on the declared channel set, validated before publication.
        from .research import read_ref

        raw, initial_sha = read_ref(request.baseline_refs[0], request.subject_id)
        validate_model(raw)
        units = {
            **BASE_UNITS,
            **{f"sampled_peak_block_{channel}": "1" for channel in raw["channels"]},
        }
        model, provenance = prepare(
            request, self.name, "therapy_pkpd_model", set(units), {"output_dir", "sample_times_h"}
        )
        if initial_sha != provenance["baseline_model_sha256"]:
            raise ValueError("PK model changed during input validation")
        validate_model(model)
        times = request.settings.get("sample_times_h")
        if not isinstance(times, list) or not 2 <= len(times) <= 10000:
            raise ValueError("Provide 2..10000 sample_times_h")
        times = [number(t, "sample time") for t in times]
        if times[0] != 0 or any(a >= b for a, b in pairwise(times)):
            raise ValueError("Sample times must start at zero and strictly increase")
        schedules = [
            [] if arm.is_comparator else dose_schedule(arm.interventions[0], times[-1])
            for arm in request.plan.arms
        ]
        arms = [
            (arm.arm_id, *simulate_pk(model, doses, times))
            for arm, doses in zip(request.plan.arms, schedules, strict=True)
        ]
        provenance.update(
            model="one-compartment IV bolus first-order elimination and static Hill pore block",
            effect_site="instantaneous unbound plasma"
            if "effect_rate_h_inv" not in model
            else "first-order effect compartment",
            model_parameters=model,
        )
        return finish(
            request,
            arms,
            provenance,
            "Exposure and static channel-block model only; no action potential, QT, arrhythmia risk, therapeutic efficacy or patient outcome prediction.",
            {
                key: "channel_block" if key.startswith("sampled_peak_block_") else "exposure"
                for key in units
            },
            units,
        )
