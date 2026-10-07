#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import socket
import sys


MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_MESSAGE_BYTES = 64 * 1024 * 1024


def _encoded(path: str | None) -> str | None:
    if not path:
        return None
    raw = Path(path).read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"delegated file is too large: {path}")
    return base64.b64encode(raw).decode("ascii")


def _report(context: dict, result: dict) -> None:
    path = context.get("solver_result_path")
    if not path:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8"
        )
    except (OSError, UnicodeError, TypeError, ValueError):
        pass


def _forward_logs(response: dict, *, include_stdout: bool = False) -> None:
    if include_stdout and response.get("stdout"):
        print(str(response["stdout"]), file=sys.stdout)
    if response.get("stderr"):
        print(str(response["stderr"]), file=sys.stderr)


def _request(sock_path: str, payload: dict) -> dict:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ValueError("delegated request is too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(3600)
        sock.connect(sock_path)
        sock.sendall(encoded + b"\n")
        raw = sock.makefile("rb").readline(MAX_MESSAGE_BYTES + 1)
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("delegated response is too large")
    if not raw:
        raise RuntimeError("development backtest bridge closed the socket")
    response = json.loads(raw)
    if not isinstance(response, dict):
        raise ValueError("invalid development backtest response")
    return response


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=os.environ.get("ORLE_ASOF_CALLBACK_SOCKET"))
    parser.add_argument("--context", required=True)
    args = parser.parse_args()
    context = json.loads(Path(args.context).read_text(encoding="utf-8"))
    payload = {
        "event": "solve",
        "run_token": context.get("run_token"),
        "decision_day": context["decision_day"],
        "data_scope": context.get("data_scope", "formal"),
        "execution_date": context.get("execution_date"),
        "mode": context["mode"],
        "strategy": context.get("strategy"),
        "benchmark": context.get("benchmark"),
        "cross_section": _encoded(context.get("cross_section")),
        "factors": _encoded(context.get("factors")),
        "market_data": _encoded(context.get("market_data")),
        "borrow_slips": _encoded(context.get("borrow_slips")),
        "borrow_slip_index": _encoded(context.get("borrow_slip_index")),
        "futures": _encoded(context.get("futures")),
        "hedge_market": _encoded(context.get("hedge_market")),
        "position": _encoded(context.get("position_path")),
        "params": context.get("params") or {},
    }
    if context.get("strategy") == "sif":
        payload["portfolio_nav"] = float(context["portfolio_nav"])
    else:
        payload["total_value"] = float(context["total_value"])
    try:
        if not args.socket:
            raise ValueError("missing development backtest callback socket")
        response = _request(args.socket, payload)
        if not response.get("ok"):
            error = str(response.get("error") or "agent solver failed")
            failure_class = str(response.get("failure_class") or "").lower()
            if failure_class in {"infrastructure", "infrastructure_failure"}:
                _report(context, {
                    "infrastructure": True,
                    "error": error,
                    "solver_records": response.get("solver_records"),
                    "program_runtime_seconds": response.get("program_runtime_seconds"),
                    "watchdog_audit": response.get("watchdog_audit"),
                })
            else:
                _report(context, {
                    "failure_class": (
                        "timeout" if response.get("timeout") or failure_class == "timeout"
                        else failure_class or "program_error"
                    ),
                    "error": error,
                    "exit_code": response.get("exit_code"),
                    "timeout": bool(response.get("timeout")),
                    "missing_output": bool(response.get("missing_output")),
                    "solver_records": response.get("solver_records"),
                    "program_runtime_seconds": response.get("program_runtime_seconds"),
                    "watchdog_audit": response.get("watchdog_audit"),
                })
            _forward_logs(response)
            return 1
        output = response.get("output")
        if not isinstance(output, str):
            raise ValueError("bridge returned no target weights")
        _report(context, {
            "exit_code": response.get("exit_code"),
            "timeout": False,
            "solver_records": response.get("solver_records"),
            "program_runtime_seconds": response.get("program_runtime_seconds"),
            "watchdog_audit": response.get("watchdog_audit"),
        })
        _forward_logs(response, include_stdout=True)
        target = Path(context["output_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(output.encode("ascii"), validate=True))
        if context.get("hedge_output_path") and response.get("hedge_output"):
            Path(context["hedge_output_path"]).write_bytes(
                base64.b64decode(str(response["hedge_output"]).encode("ascii"), validate=True)
            )
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        detail = f"{type(exc).__name__}: {exc}"
        _report(context, {"infrastructure": True, "error": detail})
        print(f"ORLE_INFRASTRUCTURE_FAILURE={detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
