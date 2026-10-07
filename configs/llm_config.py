
from __future__ import annotations

import os
import json
import urllib.request
import urllib.error
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "llm_config.yaml"

_KNOWN_ENTRY_KEYS = {
    "model", "model_aliases", "api_protocol", "api_base", "api_base_env", "api_bases_env",
    "api_key_env", "api_key_fallback_envs", "temperature", "top_p", "max_tokens",
    "context_window",
    "reasoning_effort", "thinking", "output_config", "enable_thinking",
    "instructions", "pricing",
}


class LLMConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModelPricing:

    input_per_million: float
    output_per_million: float
    cache_read_per_million: float | None = None
    cache_write_per_million: float | None = None
    currency: str = "USD"
    long_context_input_tokens: int | None = None
    long_context_input_per_million: float | None = None
    long_context_output_per_million: float | None = None
    long_context_cache_read_per_million: float | None = None
    long_context_cache_write_per_million: float | None = None

    def _rates_for_prompt(self, prompt: int) -> tuple[float, float, float, float]:
        use_long = (
            self.long_context_input_tokens is not None
            and prompt > self.long_context_input_tokens
            and self.long_context_input_per_million is not None
            and self.long_context_output_per_million is not None
        )
        if use_long:
            input_rate = self.long_context_input_per_million
            output_rate = self.long_context_output_per_million
            cache_read = self.long_context_cache_read_per_million
            cache_write = self.long_context_cache_write_per_million
        else:
            input_rate = self.input_per_million
            output_rate = self.output_per_million
            cache_read = self.cache_read_per_million
            cache_write = self.cache_write_per_million
        if cache_read is None:
            cache_read = input_rate
        if cache_write is None:
            cache_write = input_rate
        return input_rate, output_rate, cache_read, cache_write

    def cost(
        self,
        *,
        prompt_tokens: int | float | None,
        completion_tokens: int | float | None,
        cached_tokens: int | float | None = 0,
        cache_creation_tokens: int | float | None = 0,
    ) -> float:
        prompt = max(0, int(prompt_tokens or 0))
        completion = max(0, int(completion_tokens or 0))
        cached = max(0, int(cached_tokens or 0))
        created = max(0, int(cache_creation_tokens or 0))
        if cached > prompt:
            cached = prompt
        if cached + created > prompt:
            created = prompt - cached
        uncached = prompt - cached - created
        input_rate, output_rate, cache_read, cache_write = self._rates_for_prompt(prompt)
        return (
            uncached * input_rate
            + cached * cache_read
            + created * cache_write
            + completion * output_rate
        ) / 1_000_000.0

    def cost_from_steps(self, steps: Any) -> float | None:
        if not isinstance(steps, list) or not steps:
            return None
        billed = False
        total = 0.0
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            metrics = step.get("metrics")
            if not isinstance(metrics, Mapping):
                continue
            extra = metrics.get("extra") if isinstance(metrics.get("extra"), Mapping) else {}
            total += self.cost(
                prompt_tokens=metrics.get("prompt_tokens"),
                completion_tokens=metrics.get("completion_tokens"),
                cached_tokens=metrics.get("cached_tokens"),
                cache_creation_tokens=extra.get("cache_creation_input_tokens"),
            )
            billed = True
        return total if billed else None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelSpec:

    name: str
    model: str
    api_protocol: str
    api_base: str
    api_key: str = field(repr=False)
    api_keys: tuple[str, ...] = field(default_factory=tuple, repr=False)
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    context_window: int | None = None
    reasoning_effort: str | None = None
    thinking: Mapping[str, Any] | None = None
    output_config: Mapping[str, Any] | None = None
    enable_thinking: bool | None = None
    instructions: str | None = None
    pricing: ModelPricing | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "model": self.model,
            "api_protocol": self.api_protocol,
            "api_base": self.api_base,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "context_window": self.context_window,
            "reasoning_effort": self.reasoning_effort,
            "thinking": self.thinking,
            "enable_thinking": self.enable_thinking,
            "instructions": self.instructions,
        }
        if self.pricing is not None:
            payload["pricing"] = self.pricing.to_dict()
        return payload


def probe_context_window(spec: ModelSpec, *, timeout: float = 5.0) -> ModelSpec:
    try:
        request = urllib.request.Request(
            spec.api_base.rstrip("/") + "/models",
            headers={
                "Authorization": "Bearer " + spec.api_key,
                "x-api-key": spec.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        records = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(records, list):
            return spec
        for record in records:
            if not isinstance(record, Mapping):
                continue
            if str(record.get("id")) != spec.model:
                continue
            for key in (
                "max_context_window",
                "max_model_len",
                "context_window",
                "max_context_length",
                "max_input_tokens",
            ):
                value = record.get(key)
                if isinstance(value, bool):
                    continue
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    return replace(spec, context_window=value)
    except (OSError, ValueError, TypeError, urllib.error.HTTPError):
        pass
    return spec


def _require(mapping: Mapping[str, Any], key: str, name: str) -> Any:
    if key not in mapping:
        raise LLMConfigError(f"model {name!r} is missing required field {key!r}")
    return mapping[key]


def _optional_instructions(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LLMConfigError(f"model {name!r} instructions must be a string")
    text = value.strip()
    if not text:
        raise LLMConfigError(
            f"model {name!r} instructions is empty; Responses would fall back "
            "to the gateway Codex prompt"
        )
    return text


def _resolve_env(value: Any, *, name: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LLMConfigError(f"model {name!r} field {field_name!r} must be an env var name")
    resolved = os.environ.get(value.strip(), "")
    if not resolved.strip():
        raise LLMConfigError(
            f"model {name!r}: environment variable {value!r} ({field_name}) is not set"
        )
    return resolved.strip()


def _load_models(*, config_path: str | Path | None = None) -> Mapping[str, Any]:
    path = Path(config_path) if config_path else CONFIG_PATH
    if not path.is_file():
        raise LLMConfigError(f"model config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models = document.get("models")
    if not isinstance(models, Mapping):
        raise LLMConfigError(f"{path} has no models mapping")
    return models


def _parse_rate(value: Any, *, field_name: str, name: str) -> float | None:
    if value is None:
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigError(
            f"model {name!r} pricing.{field_name} must be a number (per 1M tokens)"
        ) from exc
    if rate < 0:
        raise LLMConfigError(
            f"model {name!r} pricing.{field_name} must be >= 0, got {rate}"
        )
    return rate


def parse_pricing(raw: Any, *, name: str) -> ModelPricing | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise LLMConfigError(f"model {name!r} pricing must be a mapping")
    input_rate = _parse_rate(raw.get("input_per_million"), field_name="input_per_million", name=name)
    output_rate = _parse_rate(
        raw.get("output_per_million"), field_name="output_per_million", name=name
    )
    if input_rate is None or output_rate is None:
        return None
    cache_rate = _parse_rate(
        raw.get("cache_read_per_million"),
        field_name="cache_read_per_million",
        name=name,
    )
    cache_write = _parse_rate(
        raw.get("cache_write_per_million"),
        field_name="cache_write_per_million",
        name=name,
    )
    currency = str(raw.get("currency") or "USD").strip().upper()
    if currency not in {"USD", "CNY"}:
        raise LLMConfigError(
            f"model {name!r} pricing.currency must be USD or CNY, got {currency!r}"
        )
    long_tokens = raw.get("long_context_input_tokens")
    long_context_input_tokens = None
    if long_tokens is not None:
        try:
            long_context_input_tokens = int(long_tokens)
        except (TypeError, ValueError) as exc:
            raise LLMConfigError(
                f"model {name!r} pricing.long_context_input_tokens must be an integer"
            ) from exc
        if long_context_input_tokens < 0:
            raise LLMConfigError(
                f"model {name!r} pricing.long_context_input_tokens must be >= 0"
            )
    return ModelPricing(
        input_per_million=input_rate,
        output_per_million=output_rate,
        cache_read_per_million=cache_rate,
        cache_write_per_million=cache_write,
        currency=currency,
        long_context_input_tokens=long_context_input_tokens,
        long_context_input_per_million=_parse_rate(
            raw.get("long_context_input_per_million"),
            field_name="long_context_input_per_million",
            name=name,
        ),
        long_context_output_per_million=_parse_rate(
            raw.get("long_context_output_per_million"),
            field_name="long_context_output_per_million",
            name=name,
        ),
        long_context_cache_read_per_million=_parse_rate(
            raw.get("long_context_cache_read_per_million"),
            field_name="long_context_cache_read_per_million",
            name=name,
        ),
        long_context_cache_write_per_million=_parse_rate(
            raw.get("long_context_cache_write_per_million"),
            field_name="long_context_cache_write_per_million",
            name=name,
        ),
    )


def _model_refs(name: str, entry: Mapping[str, Any]) -> set[str]:
    refs = {name, str(entry.get("model") or "")}
    aliases = entry.get("model_aliases") or []
    if isinstance(aliases, (list, tuple)):
        refs.update(str(alias) for alias in aliases if alias)
    refs.discard("")
    return refs


def load_model_pricing(
    ref: str, *, config_path: str | Path | None = None
) -> tuple[str, ModelPricing] | None:
    models = _load_models(config_path=config_path)
    entry = models.get(ref)
    name = ref
    if not isinstance(entry, Mapping):
        for logical, candidate in models.items():
            if isinstance(candidate, Mapping) and ref in _model_refs(logical, candidate):
                entry = candidate
                name = logical
                break
        else:
            return None
    pricing = parse_pricing(entry.get("pricing"), name=name)
    if pricing is None:
        return None
    return name, pricing


def cost_for_model(
    ref: str,
    *,
    prompt_tokens: int | float | None,
    completion_tokens: int | float | None,
    cached_tokens: int | float | None = 0,
    cache_creation_tokens: int | float | None = 0,
    steps: Any = None,
    config_path: str | Path | None = None,
) -> tuple[str, ModelPricing, float] | None:
    loaded = load_model_pricing(ref, config_path=config_path)
    if loaded is None:
        return None
    name, pricing = loaded
    stepped = pricing.cost_from_steps(steps)
    if stepped is not None:
        return name, pricing, stepped
    return name, pricing, pricing.cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )


cost_usd_for_model = cost_for_model


def load_model_spec(name: str, *, config_path: str | Path | None = None) -> ModelSpec:
    models = _load_models(config_path=config_path)
    if name not in models:
        known = ", ".join(sorted(models))
        raise LLMConfigError(f"unknown model {name!r}; llm_config.yaml has: {known}")
    entry = models[name]
    if not isinstance(entry, Mapping):
        raise LLMConfigError(f"model {name!r} entry must be a mapping")

    protocol = str(_require(entry, "api_protocol", name))
    configured_base = entry.get("api_base")
    if configured_base is not None:
        if not isinstance(configured_base, str) or not configured_base.strip():
            raise LLMConfigError(f"model {name!r} field 'api_base' must be a non-empty URL")
        api_base = configured_base.strip()
    else:
        api_base = _resolve_env(
            entry.get("api_base_env") or entry.get("api_bases_env"),
            name=name, field_name="api_base_env/api_bases_env",
        )
    api_base = api_base.split(",")[0].strip().rstrip("/")
    api_key = _resolve_env(entry.get("api_key_env"), name=name, field_name="api_key_env")
    fallback_envs = entry.get("api_key_fallback_envs", [])
    if not isinstance(fallback_envs, list) or not all(isinstance(x, str) for x in fallback_envs):
        raise LLMConfigError(f"model {name!r} api_key_fallback_envs must be a list of environment names")
    api_keys = tuple(dict.fromkeys([api_key] + [
        _resolve_env(env, name=name, field_name="api_key_fallback_envs")
        for env in fallback_envs
    ]))

    temperature = entry.get("temperature")
    top_p = entry.get("top_p")
    max_tokens = entry.get("max_tokens")
    return ModelSpec(
        name=name,
        model=str(_require(entry, "model", name)),
        api_protocol=protocol,
        api_base=api_base,
        api_key=api_key,
        api_keys=api_keys,
        temperature=float(temperature) if temperature is not None else None,
        top_p=float(top_p) if top_p is not None else None,
        max_tokens=int(max_tokens) if max_tokens is not None else None,
        context_window=(
            int(entry["context_window"])
            if entry.get("context_window") is not None else None
        ),
        reasoning_effort=entry.get("reasoning_effort"),
        thinking=entry.get("thinking"),
        output_config=entry.get("output_config"),
        enable_thinking=entry.get("enable_thinking"),
        instructions=_optional_instructions(entry.get("instructions"), name=name),
        pricing=parse_pricing(entry.get("pricing"), name=name),
        extra={k: v for k, v in entry.items() if k not in _KNOWN_ENTRY_KEYS},
    )


def available_models(*, config_path: str | Path | None = None) -> list[str]:
    path = Path(config_path) if config_path else CONFIG_PATH
    if not path.is_file():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models = document.get("models")
    if not isinstance(models, Mapping):
        return []
    return sorted(
        name
        for name, entry in models.items()
        if isinstance(entry, Mapping) and entry.get("api_protocol")
    )


__all__ = [
    "ModelSpec",
    "ModelPricing",
    "LLMConfigError",
    "load_model_spec",
    "probe_context_window",
    "load_model_pricing",
    "cost_for_model",
    "cost_usd_for_model",
    "parse_pricing",
    "available_models",
    "CONFIG_PATH",
    "REPO_ROOT",
]
