from __future__ import annotations

import json

from _line_rules import weighted_completion


def _load_json(path: str) -> object:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def evaluate(input_file: str, output_file: str) -> float:
    return weighted_completion(_load_json(output_file), _load_json(input_file))
