
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_native_registry: dict[str, Any] = {}


def register_optimizer(optimizer_id: str, optimizer_instance: Any) -> None:
    _native_registry[optimizer_id] = optimizer_instance
    logger.debug("Registered native optimizer: %s", optimizer_id)


def get_optimizer(optimizer_instance_id: str) -> Any:
    if optimizer_instance_id in _native_registry:
        logger.debug("Resolved '%s' from native registry", optimizer_instance_id)
        return _native_registry[optimizer_instance_id]

    available = list(_native_registry.keys())
    raise KeyError(
        f"Optimizer '{optimizer_instance_id}' not found in native registry. "
        f"Available: {available}. "
        f"Did you forget to call register_optimizer() in your entry point?"
    )
