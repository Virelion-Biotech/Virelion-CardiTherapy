"""Prescribed nonconducting lesion experiments on a weighted cardiac graph.

Binary lesion removal is a restricted topology experiment, not thermal lesion
formation, reentry simulation, ablation targeting or clinical success prediction.
"""

from __future__ import annotations

import heapq
import math

from .models import InterventionRunRequest
from .research import finish, index, number, prepare

ENDPOINT_UNITS = {
    "lesion_node_fraction": "1",
    "viable_reached_fraction": "1",
    "unreachable_viable_nodes": "count",
    "activation_span_reachable_ms": "ms",
}


def validate_graph(data):
    if set(data) != {"subject_id", "nodes_mm", "edges", "roots"}:
        raise ValueError("Conduction graph requires exactly subject_id, nodes_mm, edges and roots")
    nodes = data["nodes_mm"]
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 10000:
        raise ValueError("Graph requires 2..10000 nodes")
    for point in nodes:
        if not isinstance(point, list) or len(point) != 3:
            raise ValueError("nodes_mm must contain 3D coordinate rows")
        for value in point:
            number(value, "coordinate", minimum=-1e6)
        if any(abs(value) > 1e6 for value in point):
            raise ValueError("Coordinate magnitude exceeds 1e6 mm")
    if len({tuple(point) for point in nodes}) != len(nodes):
        raise ValueError("Duplicate graph coordinates")
    edges = data["edges"]
    if not isinstance(edges, list) or not 1 <= len(edges) <= 100000:
        raise ValueError("Graph requires 1..100000 undirected edges")
    adjacency = [[] for _ in nodes]
    seen = set()
    for edge in edges:
        if not isinstance(edge, list) or len(edge) != 3:
            raise ValueError("Each edge is [node_a,node_b,travel_time_ms]")
        a, b = index(edge[0], len(nodes)), index(edge[1], len(nodes))
        key = tuple(sorted((a, b)))
        if a == b or key in seen:
            raise ValueError("Self or duplicate graph edge")
        seen.add(key)
        cost = number(edge[2], "edge travel time", positive=True)
        adjacency[a].append((b, cost))
        adjacency[b].append((a, cost))
    roots = data["roots"]
    if not isinstance(roots, list) or not roots:
        raise ValueError("Graph requires activation roots")
    seen = set()
    for root in roots:
        if not isinstance(root, dict) or set(root) != {"node", "time_ms"}:
            raise ValueError("Roots require node/time_ms")
        node = index(root["node"], len(nodes))
        number(root["time_ms"], "root time")
        if node in seen:
            raise ValueError("Duplicate activation root")
        seen.add(node)
    return adjacency


def lesion_nodes(intervention, nodes):
    if (
        intervention.kind != "ablation"
        or intervention.target != "conduction_graph"
        or intervention.model_service not in {None, "CardiTherapy"}
        or intervention.model_capability not in {None, "therapy.run"}
    ):
        raise ValueError("Graph ablation requires ablation targeted at conduction_graph")
    parameters = intervention.parameters
    if set(parameters) == {"lesion_nodes"}:
        values = parameters["lesion_nodes"]
        if not isinstance(values, list) or not values:
            raise ValueError("lesion_nodes must be a nonempty index list")
        selected = {index(v, len(nodes)) for v in values}
        if len(selected) != len(values):
            raise ValueError("Duplicate lesion nodes")
    elif set(parameters) == {"center_mm", "radius_mm"}:
        center = parameters["center_mm"]
        if not isinstance(center, list) or len(center) != 3:
            raise ValueError("Lesion center requires three mm coordinates")
        for v in center:
            number(v, "lesion center", minimum=-1e6)
        radius = number(parameters["radius_mm"], "lesion radius", positive=True)
        selected = {i for i, point in enumerate(nodes) if math.dist(point, center) <= radius}
        if not selected:
            raise ValueError("Prescribed spherical lesion selects no graph nodes")
    else:
        raise ValueError("Lesion requires explicit lesion_nodes or center_mm/radius_mm only")
    return selected


def propagate(adjacency, roots, removed):
    times = [math.inf] * len(adjacency)
    queue = []
    for root in roots:
        if root["node"] in removed:
            raise ValueError("Lesion cannot remove an activation root")
        times[root["node"]] = root["time_ms"]
        heapq.heappush(queue, (root["time_ms"], root["node"]))
    while queue:
        time, node = heapq.heappop(queue)
        if time != times[node]:
            continue
        for neighbor, cost in adjacency[node]:
            if neighbor in removed:
                continue
            arrival = time + cost
            if not math.isfinite(arrival):
                raise ValueError("Graph arrival time overflow")
            if arrival < times[neighbor]:
                times[neighbor] = arrival
                heapq.heappush(queue, (arrival, neighbor))
    viable = len(times) - len(removed)
    reached = [t for i, t in enumerate(times) if i not in removed and math.isfinite(t)]
    metrics = {
        "lesion_node_fraction": len(removed) / len(times),
        "viable_reached_fraction": len(reached) / viable,
        "unreachable_viable_nodes": float(viable - len(reached)),
        "activation_span_reachable_ms": max(reached) - min(reached),
    }
    return metrics, {
        "activation_ms": [t if math.isfinite(t) else None for t in times],
        "lesion_nodes": sorted(removed),
        "unreachable_viable_nodes": [
            i for i, t in enumerate(times) if i not in removed and not math.isfinite(t)
        ],
        "metrics": metrics,
        "lesion_fraction_definition": "node fraction; not volume or mass fraction",
    }


class GraphAblationBackend:
    name = "graph-ablation-v1"

    def describe(self):
        return {
            "name": self.name,
            "intervention_kinds": ["ablation"],
            "endpoints": list(ENDPOINT_UNITS),
            "endpoint_scope": "model_proxy",
            "requires": "therapy_conduction_graph",
            "patient_validated": False,
            "model": "prescribed binary lesion / shortest-path conduction",
        }

    def available(self):
        return True

    def run(self, request):
        request = InterventionRunRequest.model_validate(request.model_dump())
        data, provenance = prepare(
            request, self.name, "therapy_conduction_graph", set(ENDPOINT_UNITS), {"output_dir"}
        )
        adjacency = validate_graph(data)
        selections = [
            set() if arm.is_comparator else lesion_nodes(arm.interventions[0], data["nodes_mm"])
            for arm in request.plan.arms
        ]
        if any(root["node"] in selected for selected in selections for root in data["roots"]):
            raise ValueError("Lesion cannot remove an activation root")
        arms = [
            (arm.arm_id, *propagate(adjacency, data["roots"], selected))
            for arm, selected in zip(request.plan.arms, selections, strict=True)
        ]
        provenance.update(
            model="weighted undirected shortest-path propagation with binary nonconducting nodes",
            lesion_model="prescribed mask; no thermal injury or healing model",
        )
        return finish(
            request,
            arms,
            provenance,
            "Prescribed-lesion graph experiment only; no reentry, thermal lesion formation, arrhythmia termination or patient benefit model.",
            {
                key: "lesion" if key == "lesion_node_fraction" else "conduction"
                for key in ENDPOINT_UNITS
            },
            ENDPOINT_UNITS,
        )
