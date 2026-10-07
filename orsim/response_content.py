
import re
from collections.abc import Mapping
from typing import Any


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump(mode="json", exclude_unset=True))
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__dict__"):
        return {k: _plain(v) for k, v in vars(value).items() if not k.startswith("_")}
    return {"unsupported_type": type(value).__name__}


def response_reasoning_audit(response: Any) -> dict[str, Any]:
    raw = _plain(response)
    envelope = raw if isinstance(raw, dict) else {}
    choices = envelope.get("choices") or []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message", envelope)
    message = message if isinstance(message, dict) else {}
    fields = {}
    pieces = []
    sources = []
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = message.get(key)
        state = ("missing" if key not in message else "null" if value is None
                 else "empty" if value == "" else "text" if isinstance(value, str)
                 else "unsupported_type")
        fields[key] = state
        if state == "text":
            pieces.append(value)
            sources.append(key)
    content = message.get("content")
    if isinstance(content, str):
        tagged = re.findall(r"<think\b[^>]*>(.*?)</think\s*>", content, re.I | re.S)
        if tagged:
            pieces.extend(tagged)
            sources.append("content.think_tags")
    return {
        "reasoning_content": "\n".join(pieces),
        "extraction_sources": sources,
        "field_states": fields,
        "status": "captured" if pieces else "no_recognized_reasoning_text",
        "finish_reason": choice.get("finish_reason"),
        "usage": envelope.get("usage"),
        "response_id": envelope.get("id"),
        "model": envelope.get("model"),
        "raw_message": message,
        "capture_layer": "parsed_sdk_response",
    }


def response_reasoning_content(response: Any) -> str:
    return response_reasoning_audit(response)["reasoning_content"]


def final_answer_text(content: str) -> str:
    text = str(content)
    closing = list(re.finditer(r"</think\s*>", text, re.IGNORECASE))
    if closing:
        text = text[closing[-1].end():]
    if re.search(r"<think\b", text, re.IGNORECASE):
        raise ValueError("simulator returned unfinished reasoning without an answer")
    text = text.strip()
    if not text:
        raise ValueError("simulator returned no final answer")
    return text
