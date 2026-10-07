
from __future__ import annotations


def build_run_label(
    weight_path: str,
    vwapopen: str | None = None,
    vwapclose: str | None = None,
    suffix: str = "",
) -> str:
    model_name = weight_path.split("/")[-1].split(".")[0]
    if vwapopen is not None:
        model_name += f"_{vwapopen}"
    if vwapclose is not None:
        model_name += f"_{vwapclose}"
    model_name += suffix
    return model_name
