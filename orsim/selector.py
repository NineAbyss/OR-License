
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from orsim import prompts
from orsim.language import normalize_language
from orsim.ledger import Ledger
from orsim.response_content import final_answer_text, response_reasoning_content, response_reasoning_audit


logger = logging.getLogger(__name__)

_API_RETRY_DELAYS_SECONDS = (1, 2, 4, 8, 8)
_EMPTY_BODY_RETRY_DELAYS_SECONDS = (1, 2, 4, 8, 8)


def _response_text(value: Any) -> str:
    if isinstance(value, str):
        return final_answer_text(value)
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False)
    choices = getattr(value, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if content:
            if getattr(choices[0], "finish_reason", None) == "length":
                raise ValueError("selector response was truncated")
            return final_answer_text(content)
    raise ValueError("selector returned no content")


def _response_body_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False)
    choices = getattr(value, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    return str(getattr(message, "content", None) or "")


def _has_answer_body(text: str) -> bool:
    stripped = re.sub(r"<think\b[^>]*>.*?</think\s*>", "", text, flags=re.I | re.S)
    stripped = re.sub(r"<think\b[^>]*>.*\Z", "", stripped, flags=re.I | re.S)
    return bool(stripped.strip())


def _parse_json(raw: str) -> Mapping[str, Any]:
    candidates = [raw.strip()]
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.I | re.S)
    )
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, Mapping):
                return value
        except json.JSONDecodeError:
            pass
        for match in re.finditer(r"\{", candidate):
            try:
                value, _ = decoder.raw_decode(candidate[match.start() :])
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                return value
    raise ValueError("selector did not return a JSON object")


@dataclass(frozen=True)
class SelectionResult:
    fact_ids: tuple[str, ...]
    response: str = ""
    source: str = "llm"
    raw_response: str = ""
    warning: str = ""
    reasoning_content: str = ""
    retry_reasoning_content: tuple[str, ...] = ()
    reasoning_audit: Mapping[str, Any] = field(default_factory=dict)
    retry_reasoning_audits: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_ids": list(self.fact_ids),
            "response": self.response,
            "source": self.source,
            "warning": self.warning,
            "raw_response": self.raw_response,
            "reasoning_content": self.reasoning_content,
            "retry_reasoning_content": list(self.retry_reasoning_content),
            "reasoning_audit": dict(self.reasoning_audit),
            "retry_reasoning_audits": list(self.retry_reasoning_audits),
        }


class FlatFactSelector:

    def __init__(
        self,
        ledger: Ledger,
        *,
        client: Any | None = None,
        model_id: str = "",
        max_selected_facts: int | None = None,
        max_tokens: int = 2048,
        request_kwargs: Mapping[str, Any] | None = None,
        language: str | None = None,
    ) -> None:
        self.ledger = ledger
        self.client = client
        self.model_id = model_id
        self.max_selected_facts = max_selected_facts
        self.max_tokens = int(max_tokens)
        self.request_kwargs = dict(request_kwargs or {})
        self.language = normalize_language(language)
        if self.max_tokens < 1:
            raise ValueError("selector max_tokens must be positive")

    def _catalog(self) -> list[dict[str, str]]:
        return [
            {"fact_id": fact.fact_id, "text": fact.render()}
            for fact in self.ledger
            if fact.render()
        ]

    def _prompt(self, query: str) -> str:
        return prompts.for_language(self.language).selector(
            query,
            json.dumps(self._catalog(), ensure_ascii=False),
        )

    def _invoke(self, query: str) -> Any:
        prompt = self._prompt(query)
        if callable(self.client) and not hasattr(self.client, "chat"):
            try:
                response = self.client(
                    query=query,
                    prompt=prompt,
                    facts=self._catalog(),
                    temperature=0,
                    max_tokens=self.max_tokens,
                )
            except TypeError:
                response = self.client(prompt)
        else:
            if not self.model_id:
                raise ValueError("selector model_id is required")
            request_kwargs = {
                "model": self.model_id,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
            }
            request_kwargs.update(self.request_kwargs)
            response = self.client.chat.completions.create(**request_kwargs)
        return response

    def _parse_response(self, response: Any) -> SelectionResult:
        raw = _response_text(response)
        try:
            return replace(
                self._parse_selection_json(raw),
                reasoning_content=response_reasoning_content(response),
                reasoning_audit=response_reasoning_audit(response),
            )
        except Exception as exc:
            exc.selector_raw_response = raw
            raise

    def _parse_selection_json(self, raw: str) -> SelectionResult:
        payload = _parse_json(raw)
        raw_ids = payload.get(
            "fact_ids", payload.get("selected_fact_ids", payload.get("facts", []))
        )
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        if not isinstance(raw_ids, Sequence):
            raise ValueError("selector fact_ids must be an array")
        selected: list[str] = []
        for raw_id in raw_ids:
            fact_id = str(raw_id).strip()
            if fact_id in self.ledger and fact_id not in selected:
                selected.append(fact_id)
        if self.max_selected_facts is not None:
            selected = selected[: max(0, int(self.max_selected_facts))]
        return SelectionResult(
            fact_ids=tuple(selected),
            response=str(payload.get("response", payload.get("answer", ""))).strip(),
            source="llm",
            raw_response=raw,
        )

    def _call_with_retries(
        self, query: str
    ) -> SelectionResult:
        api_retries = 0
        empty_body_retries = 0
        retry_reasoning: list[str] = []
        retry_audits: list[Mapping[str, Any]] = []
        while True:
            try:
                response = self._invoke(query)
            except Exception as exc:
                if api_retries == len(_API_RETRY_DELAYS_SECONDS):
                    if retry_reasoning:
                        exc.simulator_diagnostics = {
                            **getattr(exc, "simulator_diagnostics", {}),
                            "retry_reasoning_content": list(retry_reasoning),
                            "retry_reasoning_audits": list(retry_audits),
                        }
                    raise
                delay = _API_RETRY_DELAYS_SECONDS[api_retries]
                api_retries += 1
                logger.warning(
                    "Flat fact selector API call failed; retry %d/%d in %s seconds: %s",
                    api_retries,
                    len(_API_RETRY_DELAYS_SECONDS),
                    delay,
                    exc,
                )
                time.sleep(delay)
                continue
            try:
                return replace(
                    self._parse_response(response),
                    retry_reasoning_content=tuple(retry_reasoning),
                    retry_reasoning_audits=tuple(retry_audits),
                )
            except Exception as exc:
                choices = getattr(response, "choices", None) or []
                choice = choices[0] if choices else None
                message = getattr(choice, "message", None)
                usage = getattr(response, "usage", None)
                content = _response_body_text(response)
                diagnostics = {
                    "stage": "fact_selection_response_validation",
                    "reasoning_audit": response_reasoning_audit(response),
                    "retry_reasoning_audits": list(retry_audits),
                    "finish_reason": getattr(choice, "finish_reason", None),
                    "content_chars": len(content),
                    "reasoning_chars": len(str(getattr(message, "reasoning_content", None) or "")),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "empty_body_retries": empty_body_retries,
                    "empty_body_retry_limit": len(_EMPTY_BODY_RETRY_DELAYS_SECONDS),
                    "empty_length_retries": empty_body_retries,
                    "raw_response": getattr(exc, "selector_raw_response", ""),
                    "reasoning_content": response_reasoning_content(response),
                    "retry_reasoning_content": list(retry_reasoning),
                }
                exc.simulator_diagnostics = diagnostics
                log_diagnostics = {
                    key: value for key, value in diagnostics.items()
                    if key not in {"raw_response", "reasoning_content", "retry_reasoning_content", "reasoning_audit", "retry_reasoning_audits"}
                }
                if (
                    not _has_answer_body(content)
                    and empty_body_retries < len(_EMPTY_BODY_RETRY_DELAYS_SECONDS)
                ):
                    delay = _EMPTY_BODY_RETRY_DELAYS_SECONDS[empty_body_retries]
                    empty_body_retries += 1
                    retry_reasoning.append(diagnostics["reasoning_content"])
                    retry_audits.append(diagnostics["reasoning_audit"])
                    logger.warning(
                        "Flat fact selector returned no body (finish_reason=%s); "
                        "retry %d/%d in %s seconds: %s",
                        diagnostics["finish_reason"],
                        empty_body_retries,
                        len(_EMPTY_BODY_RETRY_DELAYS_SECONDS),
                        delay,
                        log_diagnostics,
                    )
                    time.sleep(delay)
                    continue
                logger.error(
                    "Flat fact selector response validation failed (%s): %s",
                    type(exc).__name__, log_diagnostics,
                )
                raise

    def select(self, query: str) -> SelectionResult:
        if self.client is None:
            raise RuntimeError("fact selection requires a configured LLM client")
        if not callable(self.client) and not self.model_id:
            raise ValueError("selector model_id is required")
        return self._call_with_retries(query)
