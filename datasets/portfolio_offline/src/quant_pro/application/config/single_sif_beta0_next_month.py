from pathlib import Path
import yaml


def load_single_sif_beta0_next_month_config(path):
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("benchmark") != "IN000905":
        raise ValueError("SIF replay requires benchmark IN000905")
    return [config]
