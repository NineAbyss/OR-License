from __future__ import annotations

import argparse
import json
import os
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from configs.llm_config import load_model_spec

SPEC = None
UPSTREAM = ""
KEYS = ()
KEY_INDEX = 0
KEY_LOCK = threading.Lock()
RETRY_DELAYS = (2, 4, 8, 16)
RETRY_STATUSES = {403, 429, 500, 502, 503, 504}
PROXY_LOG = Path(__file__).resolve().parents[1] / "logs/openai_anthropic_proxy.jsonl"


def _log(event, **fields):
    try:
        PROXY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with PROXY_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": time.time(), "event": event, **fields}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                if item.get("type") in {"text", "input_text"}:
                    parts.append(str(item.get("text") or ""))
                elif item.get("content"):
                    parts.append(str(item["content"]))
            elif item:
                parts.append(str(item))
        return "\n".join(x for x in parts if x)
    return str(value)


def _anthropic_content(content, *, role="user"):
    if isinstance(content, str):
        return content
    blocks = []
    for item in content or []:
        if not isinstance(item, dict):
            blocks.append({"type": "text", "text": str(item)})
            continue
        typ = item.get("type")
        if typ in {"text", "input_text"}:
            blocks.append({"type": "text", "text": item.get("text") or ""})
        elif typ == "image_url":
            url = (item.get("image_url") or {}).get("url", "")
            if url.startswith("data:") and "," in url:
                meta, data = url.split(",", 1)
                media = meta[5:].split(";", 1)[0]
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
        elif typ == "tool_use":
            blocks.append(item)
        elif typ == "tool_result":
            blocks.append(item)
    return blocks or ""


def to_anthropic(payload):
    system = []
    messages = []
    for message in payload.get("messages") or []:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system.append(_text(content))
            continue
        if role == "tool":
            block = {"type": "tool_result", "tool_use_id": message.get("tool_call_id", ""),
                     "content": _text(content)}
            if messages and messages[-1].get("role") == "user" and isinstance(messages[-1].get("content"), list):
                messages[-1]["content"].append(block)
            else:
                messages.append({"role": "user", "content": [block]})
            continue
        blocks = []
        if content not in (None, "", []):
            converted = _anthropic_content(content, role=role)
            if isinstance(converted, list):
                blocks.extend(converted)
            elif converted:
                blocks.append({"type": "text", "text": converted})
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                args = {}
            blocks.append({"type": "tool_use", "id": call.get("id") or ("toolu_" + uuid.uuid4().hex[:12]),
                           "name": fn.get("name") or "", "input": args})
        messages.append({"role": "assistant" if role == "assistant" else "user",
                         "content": blocks or ""})
    out = {"model": SPEC.model, "messages": messages,
           "max_tokens": payload.get("max_tokens") or SPEC.max_tokens or 131072}
    if system:
        out["system"] = "\n\n".join(x for x in system if x)
    if payload.get("temperature") is not None:
        out["temperature"] = payload["temperature"]
    if payload.get("top_p") is not None:
        out["top_p"] = payload["top_p"]
    if SPEC.thinking:
        out["thinking"] = dict(SPEC.thinking)
    if SPEC.output_config:
        out["output_config"] = dict(SPEC.output_config)
    tools = []
    for tool in payload.get("tools") or []:
        fn = tool.get("function") or {}
        tools.append({"name": fn.get("name") or "", "description": fn.get("description") or "",
                      "input_schema": fn.get("parameters") or {"type": "object"}})
    if tools:
        out["tools"] = tools
    return out


def from_anthropic(response, original):
    content = response.get("content") or []
    text_parts = []
    reasoning_parts = []
    calls = []
    for block in content:
        typ = block.get("type") if isinstance(block, dict) else None
        if typ == "text":
            text_parts.append(block.get("text") or "")
        elif typ in {"thinking", "redacted_thinking"}:
            reasoning_parts.append(block.get("thinking") or block.get("text") or "")
        elif typ == "tool_use":
            calls.append({"id": block.get("id") or ("call_" + uuid.uuid4().hex[:12]), "type": "function",
                          "function": {"name": block.get("name") or "", "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False)}})
    message = {"role": "assistant", "content": "\n".join(x for x in text_parts if x) or None}
    if reasoning_parts:
        message["reasoning_content"] = "\n".join(x for x in reasoning_parts if x)
    if calls:
        message["tool_calls"] = calls
    stop = "tool_calls" if calls else ("length" if response.get("stop_reason") == "max_tokens" else "stop")
    usage = response.get("usage") or {}
    return {"id": response.get("id") or ("chatcmpl_" + uuid.uuid4().hex), "object": "chat.completion",
            "created": int(time.time()), "model": response.get("model") or SPEC.model,
            "choices": [{"index": 0, "message": message, "finish_reason": stop}],
            "usage": {"prompt_tokens": int(usage.get("input_tokens") or 0),
                      "completion_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)}}


def responses_to_anthropic(payload):
    system = []
    messages = []
    raw_input = payload.get("input", "")
    if isinstance(raw_input, str):
        raw_input = [{"role": "user", "content": raw_input}]
    for item in raw_input or []:
        if not isinstance(item, dict):
            messages.append({"role": "user", "content": str(item)})
            continue
        typ = item.get("type")
        if typ == "function_call_output":
            block = {"type": "tool_result", "tool_use_id": item.get("call_id") or item.get("id") or "",
                     "content": _text(item.get("output"))}
            if messages and messages[-1].get("role") == "user" and isinstance(messages[-1].get("content"), list):
                messages[-1]["content"].append(block)
            else:
                messages.append({"role": "user", "content": [block]})
            continue
        if typ == "function_call":
            raw_args = item.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except (TypeError, ValueError):
                args = {}
            block = {"type": "tool_use", "id": item.get("call_id") or item.get("id") or ("toolu_" + uuid.uuid4().hex[:12]),
                     "name": item.get("name") or "", "input": args}
            messages.append({"role": "assistant", "content": [block]})
            continue
        role = item.get("role", "user")
        content = item.get("content", "")
        if role == "system":
            system.append(_text(content))
            continue
        if isinstance(content, list):
            blocks = []
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"input_text", "text"}:
                    blocks.append({"type": "text", "text": part.get("text") or ""})
                elif isinstance(part, dict) and part.get("type") == "output_text":
                    blocks.append({"type": "text", "text": part.get("text") or ""})
                elif isinstance(part, str):
                    blocks.append({"type": "text", "text": part})
            content = blocks
        messages.append({"role": "assistant" if role == "assistant" else "user", "content": content})
    out = {"model": SPEC.model, "messages": messages,
           "max_tokens": payload.get("max_output_tokens") or SPEC.max_tokens or 131072}
    instructions = payload.get("instructions")
    if instructions:
        system.insert(0, _text(instructions))
    if system:
        out["system"] = "\n\n".join(x for x in system if x)
    reasoning = payload.get("reasoning") or {}
    if SPEC.thinking:
        out["thinking"] = dict(SPEC.thinking)
    elif isinstance(reasoning, dict) and reasoning.get("effort"):
        out["thinking"] = {"type": "enabled"}
    if payload.get("temperature") is not None:
        out["temperature"] = payload["temperature"]
    if payload.get("top_p") is not None:
        out["top_p"] = payload["top_p"]
    tools = []
    for tool in payload.get("tools") or []:
        if tool.get("type") != "function":
            continue
        tools.append({"name": tool.get("name") or "", "description": tool.get("description") or "",
                      "input_schema": tool.get("parameters") or {"type": "object"}})
    if tools:
        out["tools"] = tools
    return out


def from_anthropic_responses(response):
    content = response.get("content") or []
    output = []
    text_parts = []
    calls = []
    for block in content:
        typ = block.get("type") if isinstance(block, dict) else None
        if typ == "text":
            text = block.get("text") or ""
            text_parts.append(text)
        elif typ in {"thinking", "redacted_thinking"}:
            continue
        elif typ == "tool_use":
            call_id = block.get("id") or ("call_" + uuid.uuid4().hex[:12])
            calls.append({"type": "function_call", "id": "fc_" + uuid.uuid4().hex[:12], "call_id": call_id,
                          "name": block.get("name") or "", "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False)})
    if text_parts:
        output.insert(0, {"type": "message", "id": "msg_" + uuid.uuid4().hex[:12], "role": "assistant",
                          "content": [{"type": "output_text", "text": "\n".join(text_parts), "annotations": []}]})
    output.extend(calls)
    usage = response.get("usage") or {}
    in_tok = int(usage.get("input_tokens") or 0)
    out_tok = int(usage.get("output_tokens") or 0)
    return {"id": response.get("id") or ("resp_" + uuid.uuid4().hex), "object": "response",
            "created_at": int(time.time()), "status": "completed", "model": response.get("model") or SPEC.model,
            "output": output, "output_text": "\n".join(text_parts),
            "usage": {"input_tokens": in_tok, "output_tokens": out_tok, "total_tokens": in_tok + out_tok},
            "parallel_tool_calls": False, "tool_choice": "auto"}


def upstream_call(payload):
    global KEY_INDEX
    body = json.dumps(payload, ensure_ascii=False).encode()
    with KEY_LOCK:
        start = KEY_INDEX
        for offset in range(max(1, len(KEYS))):
            slot = (start + offset) % len(KEYS) if KEYS else 0
            if KEYS:
                KEY_INDEX = slot
            for attempt, delay in enumerate((*RETRY_DELAYS, None)):
                headers = {"content-type": "application/json", "x-api-key": KEYS[slot] if KEYS else SPEC.api_key,
                           "Authorization": "Bearer " + (KEYS[slot] if KEYS else SPEC.api_key),
                           "anthropic-version": "2023-06-01"}
                try:
                    with urlopen(Request(UPSTREAM, data=body, headers=headers), timeout=7200) as resp:
                        return json.loads(resp.read().decode())
                except HTTPError as exc:
                    status = exc.code
                    exc.close()
                    if status not in RETRY_STATUSES:
                        raise
                    if delay is None:
                        break
                except (OSError, ValueError):
                    if delay is None:
                        break
                if delay is not None:
                    time.sleep(delay)
        raise RuntimeError("Anthropic upstream retry budget exhausted")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_stream(self, response):
        events = [("response.created", {"type": "response.created", "response": {"id": response["id"]}})]
        events.extend(("response.output_item.done", {"type": "response.output_item.done", "item": item})
                      for item in response.get("output") or [])
        events.extend([
            ("response.done", {"type": "response.done", "response": response}),
            ("response.completed", {"type": "response.completed", "response": response}),
        ])
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "keep-alive")
        self.end_headers()
        for name, event in events:
            self.wfile.write((f"event: {name}\ndata: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n").encode())
            self.wfile.flush()

    def do_GET(self):
        if self.path.split("?", 1)[0].rstrip("/") in {"/v1/models", "/models"}:
            self._send(200, {"object": "list", "data": [{"id": SPEC.model, "object": "model"}]})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path not in {"/v1/chat/completions", "/chat/completions", "/v1/responses", "/responses"}:
            self._send(404, {"error": {"message": "not found"}})
            return
        try:
            n = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(n))
            _log("http_request", path=path, stream=bool(payload.get("stream")), keys=sorted(payload.keys()))
            if path in {"/v1/responses", "/responses"}:
                response = from_anthropic_responses(upstream_call(responses_to_anthropic(payload)))
                if payload.get("stream"):
                    self._send_stream(response)
                else:
                    self._send(200, response)
            else:
                self._send(200, from_anthropic(upstream_call(to_anthropic(payload)), payload))
        except HTTPError as exc:
            _log("http_error", status=exc.code, error=str(exc))
            self._send(exc.code, {"error": {"message": str(exc)}})
        except Exception as exc:
            _log("http_exception", error=repr(exc))
            self._send(502, {"error": {"message": str(exc)}})


def main():
    global SPEC, UPSTREAM, KEYS
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    SPEC = load_model_spec(args.model)
    if SPEC.api_protocol != "anthropic_messages":
        raise SystemExit(f"{args.model} is not an Anthropic-Messages model")
    base = SPEC.api_base.rstrip("/")
    UPSTREAM = base if base.endswith("/messages") else base + "/v1/messages"
    KEYS = tuple(dict.fromkeys(SPEC.api_keys or (SPEC.api_key,)))
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
