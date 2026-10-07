from __future__ import annotations

import json
import os
from pathlib import Path
import socketserver
import threading
import time
import traceback

from workflow.executor import _redact_sensitive_text


class AskBridge:
    def __init__(self, simulator, socket_dir: Path, audit_dir: Path, *, max_questions=200):
        self.simulator = simulator
        self.socket_dir = socket_dir
        self.audit_dir = audit_dir
        self.max_questions = max_questions
        self.calls = 0
        self.failures = 0
        self.lock = threading.Lock()
        self.closed = False

    def _log(self, filename, record):
        with (self.audit_dir / filename).open("a", encoding="utf-8") as f:
            f.write(_redact_sensitive_text(json.dumps(record, ensure_ascii=False), os.environ) + "\n")

    def answer(self, request):
        if not isinstance(request, dict) or set(request) != {"query"}:
            return {"ok": False, "answer": "Expected one query string."}
        query = request["query"]
        if not isinstance(query, str) or not query.strip() or len(query.encode()) > 16384:
            return {"ok": False, "answer": "Invalid question."}
        with self.lock:
            if self.closed:
                return {"ok": False, "answer": "The task session has ended."}
            if self.calls >= self.max_questions:
                return {"ok": False, "answer": "The question limit has been reached."}
            self.calls += 1
            started = time.time()
            try:
                event = self.simulator.answer(query, update_state=True)
                selection = event.get("selection", {})
                if selection.get("source") != "llm":
                    raise RuntimeError("orsim returned an unexpected fact-selection source")
                answer = str(event.get("observation", ""))
                if not answer.strip():
                    raise ValueError("Empty simulator answer")
                answer = _redact_sensitive_text(answer, os.environ)
                self._log("ask.jsonl", {"ask_index": self.calls, "query": query,
                    "answer": answer, "event": event, "started": started,
                    "duration_seconds": time.time() - started, "status": "answered"})
                return {"ok": True, "answer": answer}
            except Exception as exc:
                self.failures += 1
                self._log("ask_errors.jsonl", {"ask_index": self.calls, "query": query,
                    "started": started, "traceback": traceback.format_exc(),
                    "simulator_diagnostics": getattr(exc, "simulator_diagnostics", {})})
                return {"ok": False, "answer": "The business information service failed."}

    def __enter__(self):
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        bridge = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(10)
                try:
                    data = self.rfile.readline(65537)
                    if len(data) > 65536 or not data.endswith(b"\n"):
                        raise ValueError("request too large or incomplete")
                    reply = bridge.answer(json.loads(data))
                except (OSError, ValueError):
                    reply = {"ok": False, "answer": "Invalid ask request."}
                try:
                    self.wfile.write(json.dumps(reply, ensure_ascii=False).encode() + b"\n")
                except OSError:
                    pass

        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True
            block_on_close = False
            slots = threading.BoundedSemaphore(16)

            def process_request(self, request, client_address):
                if not self.slots.acquire(blocking=False):
                    self.shutdown_request(request)
                    return
                try:
                    super().process_request(request, client_address)
                except BaseException:
                    self.slots.release()
                    raise

            def process_request_thread(self, request, client_address):
                try:
                    super().process_request_thread(request, client_address)
                finally:
                    self.slots.release()

        self.path = self.socket_dir / "ask.sock"
        self.server = Server(str(self.path), Handler)
        self.path.chmod(0o666)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.closed = True
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.path.unlink(missing_ok=True)
