#!/usr/bin/env python3
from __future__ import annotations

import argparse
import inspect
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import contextmanager
from typing import Any, Iterable
from urllib.parse import urlsplit

import httpx
from anthropic import Anthropic, BetaFallbackState, BetaRefusalFallbackMiddleware

PRIMARY = "claude-opus-5"
FALLBACK = "claude-opus-4-8"
HOST = "127.0.0.1"
PORT = 18086


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def error_info(exc: Exception) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)[:500]}


def is_legacy_safeguard_refusal(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "safeguards flagged this message",
        "safety classifier flagged",
        "anthropic.com/legal/aup",
    )
    return any(marker in text for marker in markers)


class FallbackProxy:
    def __init__(self, upstream: str, api_key: str, primary: str, fallback: str) -> None:
        if not upstream or not api_key:
            raise ValueError("upstream URL and API key are required")
        self.upstream = upstream.rstrip("/")
        self.primary = primary
        self.fallback = fallback
        self.client = Anthropic(
            api_key=api_key,
            base_url=self.upstream,
            timeout=7200.0,
            max_retries=0,
            middleware=[BetaRefusalFallbackMiddleware([{"model": fallback}])],
        )
        self.legacy_fallback_client = Anthropic(
            api_key=api_key,
            base_url=self.upstream,
            timeout=7200.0,
            max_retries=0,
        )
        self.create_keys = set(inspect.signature(
            self.client.beta.messages.create).parameters)
        self.stream_keys = set(inspect.signature(
            self.client.beta.messages.stream).parameters)
        self.states: dict[str, BetaFallbackState] = {}
        self.http = httpx.Client(timeout=30.0, follow_redirects=False)

    def close(self) -> None:
        self.http.close()
        self.client.close()
        self.legacy_fallback_client.close()

    def params(self, payload: dict[str, Any], streaming: bool) -> dict[str, Any]:
        allowed = self.stream_keys if streaming else self.create_keys
        params = {key: value for key, value in payload.items() if key in allowed}
        model = str(params.get("model") or self.primary)
        if model not in {self.primary, self.fallback}:
            raise ValueError("unsupported model for fallback proxy: " + model)
        params["model"] = model
        params.pop("fallbacks", None)
        params.pop("fallback_credit_token", None)
        if streaming:
            params.pop("stream", None)
        return params

    def _state(self, payload: dict[str, Any]) -> BetaFallbackState:
        prefix = {
            "metadata": payload.get("metadata"),
            "system": payload.get("system"),
            "messages": (payload.get("messages") or [])[:2],
            "tools": payload.get("tools"),
        }
        key = json.dumps(prefix, ensure_ascii=False, sort_keys=True, default=str)
        return self.states.setdefault(key, BetaFallbackState())

    def create(self, payload: dict[str, Any]) -> Any:
        state = self._state(payload)
        params = self.params(payload, False)
        try:
            with state:
                response = self.client.beta.messages.create(**params)
        except Exception as exc:
            if params.get("model") != self.primary or not is_legacy_safeguard_refusal(exc):
                raise
            params["model"] = self.fallback
            return self.legacy_fallback_client.beta.messages.create(**params)
        return response

    @contextmanager
    def stream(self, payload: dict[str, Any]) -> Iterable[Any]:
        state = self._state(payload)
        params = self.params(payload, True)
        try:
            with state:
                with self.client.beta.messages.stream(**params) as stream:
                    yield stream
        except Exception as exc:
            if params.get("model") != self.primary or not is_legacy_safeguard_refusal(exc):
                raise
            params["model"] = self.fallback
            with self.legacy_fallback_client.beta.messages.stream(**params) as stream:
                yield stream

    def models(self) -> tuple[int, str, bytes]:
        response = self.http.get(
            self.upstream + "/v1/models",
            headers={
                "x-api-key": self.client.api_key or "",
                "anthropic-version": "2023-06-01",
                "accept": "application/json",
            },
        )
        return response.status_code, response.headers.get(
            "content-type", "application/json"), response.content


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    proxy: FallbackProxy

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def send_bytes(self, status: int, body: bytes,
                   content_type: str = "application/json") -> None:
        self.close_connection = True
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, value: Any) -> None:
        self.send_bytes(
            status,
            json.dumps(jsonable(value), ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8"),
        )

    def do_GET(self) -> None:
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path == "/healthz":
            self.send_json(200, {
                "status": "ok",
                "primary_model": self.proxy.primary,
                "fallback_model": self.proxy.fallback,
            })
            return
        if path == "/v1/models":
            try:
                status, content_type, body = self.proxy.models()
            except Exception as exc:
                self.send_json(502, {"error": {"type": "upstream_error",
                                               "message": str(exc)[:500]}})
                return
            self.send_bytes(status, body, content_type)
            return
        self.send_json(404, {"error": {"type": "not_found"}})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path != "/v1/messages":
            self.send_json(404, {"error": {"type": "not_found"}})
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            if bool(payload.get("stream", False)):
                self.handle_stream(payload)
            else:
                self.handle_create(payload)
        except Exception as exc:
            self.send_json(502, {"error": {"type": "fallback_proxy_error",
                                           **error_info(exc)}})

    def handle_create(self, payload: dict[str, Any]) -> None:
        try:
            response = self.proxy.create(payload)
        except Exception as exc:
            self.send_json(502, {"error": {"type": "upstream_error",
                                           **error_info(exc)}})
            return
        self.send_json(200, response)

    def handle_stream(self, payload: dict[str, Any]) -> None:
        try:
            manager = self.proxy.stream(payload)
            with manager as stream:
                self.close_connection = True
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.send_header("connection", "close")
                self.end_headers()
                for event in stream:
                    data = json.dumps(jsonable(event), ensure_ascii=False,
                                      separators=(",", ":"))
                    kind = getattr(event, "type", None) or "message"
                    self.wfile.write(
                        f"event: {kind}\ndata: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
        except Exception:
            self.close_connection = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=env("OPUS_FALLBACK_PROXY_HOST", HOST))
    parser.add_argument("--port", type=int, default=int(
        env("OPUS_FALLBACK_PROXY_PORT", str(PORT))))
    parser.add_argument("--upstream", default=env("OPUS_FALLBACK_UPSTREAM"))
    parser.add_argument("--api-key", default=env("OPUS_FALLBACK_API_KEY"))
    parser.add_argument("--primary-model", default=env(
        "OPUS_FALLBACK_PRIMARY_MODEL", PRIMARY))
    parser.add_argument("--fallback-model", default=env(
        "OPUS_FALLBACK_MODEL", FALLBACK))
    args = parser.parse_args()
    proxy = FallbackProxy(args.upstream, args.api_key,
                          args.primary_model, args.fallback_model)
    Handler.proxy = proxy
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        proxy.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
