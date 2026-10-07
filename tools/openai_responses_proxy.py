from __future__ import annotations

import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from configs.llm_config import load_model_spec

SPEC = None
UPSTREAM = ""
TOOL_REASONING = {}
PROXY_LOG = Path(__file__).resolve().parents[1] / "logs/openai_responses_proxy.jsonl"


def _log(event, **fields):
    try:
        PROXY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with PROXY_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": time.time(), "event": event, **fields}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                if item.get("type") in {"input_text", "output_text", "text"}:
                    out.append(str(item.get("text") or ""))
                elif item.get("content"):
                    out.append(str(item["content"]))
            elif item:
                out.append(str(item))
        return "\n".join(x for x in out if x)
    return str(value)


def responses_to_chat(payload):
    needs_reasoning = SPEC.model.lower().startswith("deepseek")
    messages = []
    instructions = payload.get("instructions")
    if instructions:
        messages.append({"role": "system", "content": text(instructions)})
    raw_input = payload.get("input", "")
    if isinstance(raw_input, str):
        raw_input = [{"role": "user", "content": raw_input}]
    pending_reasoning = None
    for item in raw_input or []:
        if not isinstance(item, dict):
            messages.append({"role": "user", "content": str(item)})
            continue
        typ = item.get("type")
        if typ == "reasoning":
            summary = item.get("summary") or []
            pieces = []
            for part in summary:
                if isinstance(part, str):
                    pieces.append(part)
                elif isinstance(part, dict):
                    pieces.append(str(part.get("text") or ""))
            pending_reasoning = "\n".join(x for x in pieces if x) or pending_reasoning
            continue
        if typ == "function_call_output":
            messages.append({"role": "tool", "tool_call_id": item.get("call_id") or item.get("id") or "",
                             "content": text(item.get("output"))})
            continue
        if typ == "function_call":
            raw = item.get("arguments") or "{}"
            call = {
                "id": item.get("call_id") or item.get("id") or ("call_" + uuid.uuid4().hex[:12]),
                "type": "function", "function": {"name": item.get("name") or "", "arguments": raw if isinstance(raw, str) else json.dumps(raw)}}
            if messages and messages[-1].get("role") == "assistant" and messages[-1].get("tool_calls"):
                messages[-1]["tool_calls"].append(call)
            else:
                msg = {"role": "assistant", "content": None, "tool_calls": [call]}
                if needs_reasoning:
                    msg["reasoning_content"] = TOOL_REASONING.get(call["id"], pending_reasoning or "")
                pending_reasoning = None
                messages.append(msg)
            continue
        role = item.get("role", "user")
        if role == "developer":
            role = "system"
        msg = {"role": role, "content": text(item.get("content", ""))}
        if role == "assistant" and pending_reasoning and needs_reasoning:
            msg["reasoning_content"] = pending_reasoning
            pending_reasoning = None
        messages.append(msg)
    out = {"model": SPEC.model, "messages": messages, "stream": False}
    for key in ("temperature", "top_p", "reasoning_effort"):
        configured = getattr(SPEC, key, None)
        if configured is not None:
            out[key] = configured
    if payload.get("max_output_tokens") is not None:
        out["max_tokens"] = payload["max_output_tokens"]
        if SPEC.max_tokens is not None:
            out["max_tokens"] = min(out["max_tokens"], SPEC.max_tokens)
    elif SPEC.max_tokens is not None:
        out["max_tokens"] = SPEC.max_tokens
    if SPEC.thinking is not None:
        out["thinking"] = dict(SPEC.thinking)
    if SPEC.enable_thinking is not None:
        out["enable_thinking"] = SPEC.enable_thinking
    for key, value in SPEC.extra.items():
        if key == "chat_template_kwargs":
            out[key] = value
    tools = []
    for tool in payload.get("tools") or []:
        if tool.get("type") == "function":
            tools.append({"type": "function", "function": {"name": tool.get("name") or "",
                          "description": tool.get("description") or "", "parameters": tool.get("parameters") or {"type": "object"}}})
    if tools:
        out["tools"] = tools
        out["tool_choice"] = payload.get("tool_choice", "auto")
    return out


def chat_to_responses(result):
    choice = (result.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    output = []
    content = text(message.get("content"))
    if content:
        output.append({"type": "message", "id": "msg_" + uuid.uuid4().hex[:12], "role": "assistant",
                       "content": [{"type": "output_text", "text": content, "annotations": []}]})
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        call_id = call.get("id") or ("call_" + uuid.uuid4().hex[:12])
        if message.get("reasoning_content") is not None:
            TOOL_REASONING[call_id] = message["reasoning_content"]
        output.append({"type": "function_call", "id": "fc_" + uuid.uuid4().hex[:12],
                       "call_id": call_id,
                       "name": fn.get("name") or "", "arguments": fn.get("arguments") or "{}"})
    usage = result.get("usage") or {}
    inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    return {"id": "resp_" + uuid.uuid4().hex, "object": "response", "created_at": int(time.time()),
            "status": "completed", "model": result.get("model") or SPEC.model, "output": output,
            "output_text": content, "usage": {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out},
            "parallel_tool_calls": False, "tool_choice": "auto"}


def call(payload):
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = Request(UPSTREAM, data=body, headers={"content-type": "application/json",
                "Authorization": "Bearer " + SPEC.api_key})
    try:
        _log("upstream_payload_shape", message_roles=[m.get("role") for m in payload.get("messages") or []],
             assistant_tool_counts=[len(m.get("tool_calls") or []) for m in payload.get("messages") or []],
             assistant_reasoning_lengths=[len(str(m.get("reasoning_content") or "")) for m in payload.get("messages") or [] if m.get("role") == "assistant"],
             tool_assistant_missing_reasoning=sum(1 for m in payload.get("messages") or [] if m.get("role") == "assistant" and m.get("tool_calls") and not m.get("reasoning_content")),
             tool_call_ids=[c.get("id") for m in payload.get("messages") or [] for c in (m.get("tool_calls") or [])],
             tool_message_ids=[m.get("tool_call_id") for m in payload.get("messages") or [] if m.get("role") == "tool"])
        with urlopen(req, timeout=7200) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:1000]
        except Exception:
            detail = ""
        _log("upstream_http_error", status=exc.code, detail=detail,
             payload_keys=sorted(payload.keys()), message_count=len(payload.get("messages") or []),
             tool_count=len(payload.get("tools") or []))
        raise


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_response_stream(self, response):
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
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in {"/v1/models", "/models"}:
            self.send_json(200, {"object": "list", "data": [{"id": SPEC.model, "object": "model"}]})
        else:
            self.send_json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path not in {"/v1/responses", "/responses"}:
            self.send_json(404, {"error": {"message": "not found"}})
            return
        try:
            n = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(n))
            _log("http_request", path=path, stream=bool(payload.get("stream")), keys=sorted(payload.keys()))
            response = chat_to_responses(call(responses_to_chat(payload)))
            if payload.get("stream"):
                self.send_response_stream(response)
            else:
                self.send_json(200, response)
        except HTTPError as exc:
            _log("http_error", status=exc.code, error=str(exc))
            self.send_json(exc.code, {"error": {"message": str(exc)}})
        except Exception as exc:
            _log("http_exception", error=repr(exc))
            self.send_json(502, {"error": {"message": str(exc)}})


def main():
    global SPEC, UPSTREAM
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    SPEC = load_model_spec(args.model)
    if SPEC.api_protocol != "openai_chat_completions":
        raise SystemExit(f"{args.model} is not an OpenAI Chat-Completions model")
    base = SPEC.api_base.rstrip("/")
    UPSTREAM = base if base.endswith("/chat/completions") else base + "/chat/completions"
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
