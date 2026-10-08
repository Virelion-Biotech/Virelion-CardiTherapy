from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .api import TherapyAPI
from .models import InterventionRunRequest
from .serialization import loads, write_json


def main() -> int:
    parser = argparse.ArgumentParser(prog="carditherapy")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Report package and backend availability")
    validate = sub.add_parser("validate", help="Validate an intervention request")
    validate.add_argument("request", type=Path)
    run = sub.add_parser("run", help="Execute a request and save its result atomically")
    run.add_argument("request", type=Path)
    run.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if args.command == "doctor":
        print(json.dumps(TherapyAPI().health(), indent=2, sort_keys=True))
        return 0
    try:
        payload = loads(args.request.read_text(encoding="utf-8"))
        request = InterventionRunRequest.model_validate(payload)
        if args.command == "validate":
            print(json.dumps({"status": "valid", "plan_id": request.plan.plan_id}))
        else:
            if args.output.resolve() == args.request.resolve():
                raise ValueError("Result output must not overwrite the request")
            from urllib.parse import urlparse

            from .pacing_backend import _local_path

            inputs = [request.twin_state_ref, *request.baseline_refs]
            if request.posterior_ref is not None:
                inputs.append(request.posterior_ref)
            for ref in inputs:
                if (
                    urlparse(ref.uri).scheme in {"", "file"}
                    and _local_path(ref.uri) == args.output.resolve()
                ):
                    raise ValueError("Result output must not overwrite an input artifact")
            result = TherapyAPI().run(payload)
            for ref in result["artifacts"]:
                if (
                    urlparse(ref["uri"]).scheme in {"", "file"}
                    and _local_path(ref["uri"]) == args.output.resolve()
                ):
                    raise ValueError("Result output must not overwrite a delegate artifact")
            write_json(args.output, result)
        return 0
    except (ValueError, TypeError, RuntimeError, OSError, KeyError) as exc:
        print(f"carditherapy: {exc}", file=sys.stderr)
        return 2
    return 2
