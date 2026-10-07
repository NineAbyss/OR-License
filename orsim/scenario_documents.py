
from pathlib import Path
from typing import Mapping, Any

import yaml


def public_documents_root(scenario: str | Path, config: Mapping[str, Any] | None = None) -> Path:
    scenario = Path(scenario)
    if config is None:
        path = scenario / "simulator_config.yaml"
        config = yaml.safe_load(path.read_text()) if path.is_file() else {}
    configured = (config or {}).get("public_documents_root", ".")
    if configured == ".":
        return scenario.resolve()
    if configured != "../problem" or scenario.name not in {"scenario", "simulator"}:
        raise ValueError("public_documents_root must be . or the sibling ../problem")
    target = scenario.parent / "problem"
    if scenario.is_symlink() or target.is_symlink() or not target.is_dir():
        raise ValueError("shared public documents must be an ordinary problem directory")
    return target.resolve()


def public_document(scenario: str | Path, name: str, config=None) -> Path:
    if config is None:
        path = Path(scenario) / "simulator_config.yaml"
        config = yaml.safe_load(path.read_text()) if path.is_file() else {}
    shared = (config or {}).get("shared_public_documents", [])
    if not isinstance(shared, list) or any(
        item not in {"brief.md", "input/problem_description.md"} for item in shared
    ):
        raise ValueError("shared_public_documents must list only public brief/description")
    if name in shared:
        config = dict(config or {}, public_documents_root="../problem")
    root = public_documents_root(scenario, config)
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("public document must stay inside its document root")
    if root != Path(scenario).resolve() and relative.as_posix() not in {
        "brief.md", "input/problem_description.md"
    }:
        raise ValueError("shared access is limited to brief and problem description")
    target = root / relative
    for parent in target.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("public document path must not contain symbolic links")
    from workflow.executor import _read_regular_child_without_links
    _read_regular_child_without_links(target.parent, target.name, label="public scenario document")
    return target
