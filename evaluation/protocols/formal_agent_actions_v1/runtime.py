
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from workflow.executor import _read_regular_child_without_links

from .policy import (
    POLICY_ID,
    AgentActionPolicy,
    load_policy,
    load_workflow_config,
    simulator_overrides,
)


def _validated_scenario_root(scenario_dir: str | Path) -> Path:

    supplied = Path(scenario_dir).expanduser()
    if supplied.is_symlink() or not supplied.is_dir():
        raise ValueError("formal orsim scenario must be an ordinary directory")
    root = supplied.resolve()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("formal orsim scenario must not contain symbolic links")
        if path.is_file():
            try:
                _read_regular_child_without_links(
                    path.parent,
                    path.name,
                    label="formal orsim scenario artifact",
                )
            except (OSError, ValueError) as exc:
                raise ValueError(
                    "formal orsim scenario artifacts must be ordinary files "
                    "with no symbolic or hard links"
                ) from exc
        elif not path.is_dir():
            raise ValueError("formal orsim scenario contains an unsupported artifact")

    config_path = root / "simulator_config.yaml"
    try:
        config = yaml.safe_load(
            _read_regular_child_without_links(
                root,
                config_path.name,
                label="formal orsim simulator config",
            ).decode("utf-8")
        ) or {}
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("formal orsim simulator config is missing or unsafe") from exc
    if not isinstance(config, Mapping):
        raise ValueError("formal orsim simulator config must be an object")
    environment = config.get("interaction_environment", {}) or {}
    if "public_documents_root" in config or "shared_public_documents" in config:
        from orsim.scenario_documents import public_document
        public_document(root, "brief.md", config)
        public_document(root, "input/problem_description.md", config)
    if not isinstance(environment, Mapping):
        raise ValueError("formal orsim interaction environment must be an object")

    references = {
        "ledger_path": environment.get("ledger_path", "interaction/ledger.json"),
    }
    for name, raw_path in references.items():
        relative = Path(str(raw_path))
        if relative.is_absolute():
            raise ValueError(f"formal orsim {name} must stay inside the scenario")
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"formal orsim {name} must stay inside the scenario")
        try:
            _read_regular_child_without_links(
                resolved.parent,
                resolved.name,
                label=f"formal orsim {name}",
            )
        except (OSError, ValueError) as exc:
            raise ValueError(f"formal orsim {name} is missing or unsafe") from exc
    return root


def build_simulator(
    scenario_dir: str | Path,
    *,
    policy: AgentActionPolicy | None = None,
    **kwargs: Any,
) -> Any:
    from orsim import Simulator

    scenario_root = _validated_scenario_root(scenario_dir)
    selected = policy or load_policy()
    overrides = simulator_overrides(selected)
    call_kwargs = dict(kwargs)
    call_kwargs.pop("response_client", None)
    call_kwargs.update(overrides)
    return Simulator.from_scenario(scenario_root, **call_kwargs)


def install_agent_protocol(policy: AgentActionPolicy | None = None) -> dict[str, Any]:
    selected = policy or load_policy()
    return {
        "protocol_id": POLICY_ID,
        "policy": selected.to_dict(),
    }


install_formal_agent_actions_protocol = install_agent_protocol


__all__ = [
    "POLICY_ID",
    "build_simulator",
    "install_agent_protocol",
    "install_formal_agent_actions_protocol",
    "load_policy",
    "load_workflow_config",
]
