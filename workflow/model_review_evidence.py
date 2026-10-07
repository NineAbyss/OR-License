from __future__ import annotations

import base64
import json
from pathlib import Path


def model_review_judge_timeout(program, base_timeout):
    path = Path(program) / "_model_review_policy.json"
    if not path.is_file():
        return base_timeout
    policy = json.loads(path.read_text())
    if policy.get("enabled") is not True:
        return base_timeout
    return None


def write_model_review_evidence(output_file, source, input_files, *, origin, epochs=None):
    output = Path(output_file)
    payload = {
        "schema_version": 2,
        "origin": origin,
        "output_b64": base64.b64encode(output.read_bytes()).decode("ascii"),
        "inputs_b64": [base64.b64encode(Path(p).read_bytes()).decode("ascii")
                          for p in sorted(input_files)],
    }
    if source is not None:
        payload["source"] = source
    if epochs is not None:
        payload["epochs"] = epochs
    path = output.with_suffix(".model_review_evidence.json")
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)
    return path
