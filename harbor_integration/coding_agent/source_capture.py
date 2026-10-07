from __future__ import annotations

import base64
import binascii
import fcntl
import re
import json
import os
from pathlib import Path
import stat
import threading
import time


SOURCE_SUFFIXES = frozenset((".py", ".sh", ".bash", ".jl", ".cpp", ".cc", ".c", ".h", ".hpp", ".rs", ".r", ".R"))
SKIP_DIRS = frozenset((".git", ".venv", "venv", "__pycache__", "node_modules"))


def _read_regular(root, relative, limit):
    parts = Path(relative).parts
    if not parts or any(p in ("..", ".", "/") for p in parts):
        raise ValueError("Invalid source path")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(child, "rb") as stream:
            st = os.fstat(stream.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > limit:
                raise ValueError("Unsafe or oversized source file")
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Oversized source file")
        return data
    finally:
        os.close(fd)


def read_source(root, relative, limit):
    return _read_regular(root, relative, limit).decode("utf-8")


def _snapshot_text(directory, snapshot, limit):
    if not isinstance(snapshot, str) or not re.fullmatch(r"snapshot_[0-9]+\.txt", snapshot):
        raise ValueError("Invalid source snapshot reference")
    return _read_regular(directory, snapshot, limit).decode("utf-8")


def _decode_payload(value):
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise ValueError("Invalid locked evidence payload") from exc


class SourceCapture:
    def __init__(self, workspace, private_dir, *, output_workspace=None,
                 limit=10 * 1024 * 1024, artifact_limit=64 * 1024 * 1024):
        self.workspace = Path(workspace)
        self.directory = Path(private_dir) / "source_snapshots"
        self.output_workspace = Path(output_workspace) if output_workspace else None
        self.artifact_directory = self.directory / "artifacts"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.limit = limit
        self.artifact_limit = artifact_limit
        self.lock = threading.Lock()

    def _store_snapshot(self, data, *, artifact=False):
        directory = self.artifact_directory if artifact else self.directory
        suffix = ".bin" if artifact else ".txt"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (directory / ".snapshot.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            existing = sorted(directory.glob("snapshot_*" + suffix))
            for path in existing:
                if _read_regular(directory, path.name, max(self.limit, self.artifact_limit)) == data:
                    return ("artifacts/" if artifact else "") + path.name
            number = len(existing) + 1
            while True:
                name = f"snapshot_{number:06d}{suffix}"
                try:
                    fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
                    break
                except FileExistsError:
                    number += 1
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            return ("artifacts/" if artifact else "") + name

    def _capture_artifacts(self):
        artifacts = []
        total = 0
        roots = [(self.workspace, "/work", True)]
        if self.output_workspace is not None:
            roots.append((self.output_workspace, "/output", False))
        for root, prefix, source_only in roots:
            if not root.is_dir():
                continue
            for base, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = sorted(
                    d for d in dirs
                    if d not in SKIP_DIRS and not (Path(base) / d).is_symlink()
                )
                for name in sorted(files):
                    path = Path(base) / name
                    if path.is_symlink():
                        raise OSError(f"Refusing artifact symlink: {path}")
                    if source_only and path.suffix in SOURCE_SUFFIXES:
                        continue
                    relative = path.relative_to(root)
                    remaining = self.artifact_limit - total
                    data = _read_regular(root, relative, remaining)
                    total += len(data)
                    if total > self.artifact_limit:
                        raise ValueError("Artifact snapshot exceeds limit")
                    blob = self._store_snapshot(data, artifact=True)
                    artifacts.append({
                        "path": prefix + "/" + str(relative),
                        "size": len(data),
                        "blob": blob,
                    })
        return artifacts

    def capture_after_solver(self, call=None, outcome="completed"):
        return self._capture(
            call=call,
            stage="after_solver_call",
            outcome=outcome,
            include_artifacts=True,
        )

    def _capture(self, pid=None, call=None, *, stage=None, outcome=None,
                 include_artifacts=False):
        with self.lock:
            event = {
                "time": time.time(),
                "stage": stage or ("before_solver_call" if call else "final_workspace"),
                "call_id": call.get("call_id") if call else None,
                "files": [],
            }
            if outcome is not None:
                event["outcome"] = outcome
            if call and call.get("cmdline"):
                event["command"] = call["cmdline"]
            if call and call.get("kind") == "rolling_commit":
                event.update(stage="hourly_commit", epoch=call["epoch"],
                             submission_b64=call["submission_b64"],
                             input_b64=call["input_b64"])
            try:
                if pid is not None:
                    cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
                    if len(cmd) > self.limit:
                        raise ValueError("Oversized solver command")
                    event["command"] = cmd.decode("utf-8").replace("\0", " ").strip()
                total = 0
                visited = 0
                for base, dirs, files in os.walk(self.workspace, followlinks=False):
                    visited += 1
                    if visited > 2048:
                        raise ValueError("Source tree too large")
                    dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(base) / d).is_symlink())
                    for name in sorted(files):
                        if Path(name).suffix not in SOURCE_SUFFIXES:
                            continue
                        relative = (Path(base) / name).relative_to(self.workspace)
                        source = read_source(self.workspace, relative, self.limit)
                        total += len(source.encode())
                        if total > self.limit or len(event["files"]) >= 256:
                            raise ValueError("Source bundle exceeds review limit")
                        snapshot = self._store_snapshot(source.encode("utf-8"))
                        event["files"].append({"path": "/work/" + str(relative), "snapshot": snapshot})
            except (OSError, ValueError) as exc:
                event["error_type"] = type(exc).__name__
            if include_artifacts:
                try:
                    event["artifacts"] = self._capture_artifacts()
                except (OSError, ValueError) as exc:
                    event["artifacts"] = []
                    event["artifact_error_type"] = type(exc).__name__
            with (self.directory / "events.jsonl").open("a") as out:
                out.write(json.dumps(event, ensure_ascii=False) + "\n")
            return event

    def capture(self, pid=None, call=None):
        return self._capture(pid=pid, call=call)


def _read_events(directory):
    path = directory / "events.jsonl"
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise ValueError(f"Source capture journal unreadable: {type(exc).__name__}")
    events = []
    for line in lines:
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            raise ValueError("Source capture journal is not recoverable")
    return events


def _solver_index(private_dir):
    index = {}
    try:
        lines = (Path(private_dir) / "solver_calls.jsonl").read_text().splitlines()
    except OSError:
        return index
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        call_id = row.get("call_id")
        if not call_id:
            continue
        entry = index.setdefault(call_id, {})
        for field in ("solver", "limit_seconds", "classification"):
            if row.get(field) is not None:
                entry[field] = row[field]
    return index


def epoch_source_bundles(private_dir, limit):
    directory = Path(private_dir) / "source_snapshots"
    events = _read_events(directory)
    commits = [e for e in events if e.get("stage") == "hourly_commit"]
    if not commits:
        raise ValueError("No hourly commit source evidence")
    commits.sort(key=lambda e: (int(e.get("epoch", 0)), e.get("time", 0)))
    journal = json.loads((Path(private_dir) / "rolling/commits.json").read_text())
    if not isinstance(journal, list) or [e.get("epoch") for e in commits] != list(range(len(journal))):
        raise ValueError("Locked rounds and source captures do not match")
    for epoch, commit in enumerate(commits):
        locked = journal[epoch]
        if _decode_payload(commit.get("submission_b64")) != _decode_payload(locked.get("payload_b64")):
            raise ValueError("Locked submission evidence mismatch")
        state = _read_regular(Path(private_dir) / "rolling/states", f"epoch_{epoch}.json", limit)
        if _decode_payload(commit.get("input_b64")) != state:
            raise ValueError("Locked input evidence mismatch")
    solver_calls = _solver_index(private_dir)

    bodies = {}
    unique_bytes = 0

    def body(snapshot):
        nonlocal unique_bytes
        if snapshot in bodies:
            return bodies[snapshot]
        try:
            text = _snapshot_text(directory, snapshot, limit)
        except OSError:
            bodies[snapshot] = None
            return None
        unique_bytes += len(text.encode())
        if unique_bytes > limit:
            raise ValueError("Oversized native source evidence")
        bodies[snapshot] = text
        return text

    boundaries = [e.get("time", 0) for e in commits]
    epochs = []
    for index, commit in enumerate(commits):
        epoch = int(commit.get("epoch", index))
        gaps = []
        if commit.get("error_type"):
            gaps.append({"kind": "commit_source_capture",
                         "reason": commit["error_type"], "epoch": epoch})
        files = []
        for record in commit.get("files") or []:
            text = body(record["snapshot"])
            if text is None:
                gaps.append({"kind": "missing_source_body", "epoch": epoch,
                             "reason": "snapshot body unavailable",
                             "path": record["path"], "snapshot": record["snapshot"]})
                continue
            files.append({"path": record["path"], "snapshot": record["snapshot"], "text": text})
        if not files:
            gaps.append({"kind": "no_source_evidence", "epoch": epoch,
                         "reason": "no frozen source for this round"})

        lower = boundaries[index - 1] if index else None
        upper = boundaries[index]
        calls = {}
        for event in events:
            if event.get("stage") not in ("before_solver_call", "after_solver_call"):
                continue
            when = event.get("time", 0)
            if when > upper or (lower is not None and when <= lower):
                continue
            if event.get("error_type"):
                gaps.append({"kind": "solver_source_capture", "epoch": epoch,
                             "reason": event["error_type"], "call_id": event.get("call_id")})
            if event.get("artifact_error_type"):
                gaps.append({"kind": "artifact_capture", "epoch": epoch,
                             "reason": event["artifact_error_type"],
                             "call_id": event.get("call_id")})
            call_id = event.get("call_id")
            if not call_id:
                continue
            entry = calls.setdefault(call_id, {"call_id": call_id, "command": "",
                                               "outcome": None, "files": []})
            if event.get("command"):
                entry["command"] = event["command"]
            if event.get("outcome"):
                entry["outcome"] = event["outcome"]
            if event.get("files"):
                entry["files"] = [{"path": r["path"], "snapshot": r["snapshot"]}
                                  for r in event["files"]]
            entry.update(solver_calls.get(call_id, {}))
        epochs.append({"epoch": epoch,
                       "submission_b64": commit.get("submission_b64"),
                       "input_b64": commit.get("input_b64"),
                       "files": files,
                       "solver_calls": sorted(calls.values(), key=lambda c: c["call_id"]),
                       "evidence_gaps": gaps})

    groups = {}
    for item in epochs:
        signature = sorted({(c.get("command", ""), c.get("solver"), c.get("limit_seconds"))
                            for c in item["solver_calls"]})
        identity = (tuple(sorted((f["path"], f["text"]) for f in item["files"])), tuple(signature))
        key = next((name for name, group in groups.items() if group["identity"] == identity),
                   f"group_{len(groups) + 1:03d}")
        item["group_key"] = key
        group = groups.setdefault(key, {"group_key": key, "epochs": [],
                                        "files": item["files"],
                                        "call_signature": [list(s) for s in signature], "identity": identity})
        group["epochs"].append(item["epoch"])
    for group in groups.values():
        group.pop("identity")
    return {"schema_version": 2, "total_epochs": len(epochs), "epochs": epochs,
            "groups": [groups[k] for k in sorted(groups, key=lambda k: groups[k]["epochs"][0])]}


def source_bundle(private_dir, limit):
    directory = Path(private_dir) / "source_snapshots"
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    if any(e.get("error_type") or e.get("artifact_error_type") for e in events):
        raise ValueError("Source/artifact capture incomplete; modeling review needs inspection")
    versions = {}
    calls = {}
    for event in events:
        if event.get("call_id"):
            command = event.get("command", "")
            key = json.dumps([command, event["files"]], sort_keys=True)
            item = calls.setdefault(key, {"command": command, "files": event["files"],
                                         "call_count": 0, "first_call_id": event["call_id"]})
            item["call_count"] += 1
            item["last_call_id"] = event["call_id"]
        for record in event["files"]:
            versions[(record["path"], record["snapshot"])] = record
    parts = ["# Host evidence: workspace source versions and observed solver-call commands.\n"
             "# Solver snapshots precede solver API execution, not the entire script; hourly commit and final snapshots are separately labeled.\n"
             "# A file's presence alone does not prove execution. Review the invoked entrypoints and actual call chain.\n",
             "# HOURLY_COMMIT_SNAPSHOTS " + json.dumps([
                 {key: value for key, value in event.items()
                  if key not in ("submission_b64", "input_b64")}
                 for event in events if event.get("stage") == "hourly_commit"
             ], ensure_ascii=False),
             "# OBSERVED_SOLVER_CALLS " + json.dumps(list(calls.values()), ensure_ascii=False),
             "# FINAL_WORKSPACE_FILES " + json.dumps(events[-1]["files"], ensure_ascii=False)]
    for (path, snapshot), record in versions.items():
        source = _snapshot_text(directory, snapshot, limit)
        parts.append(f"\n# FILE {path} SNAPSHOT {snapshot}\n{source}\n# END FILE\n")
    source = "\n".join(parts)
    if not versions or len(source.encode()) > limit:
        raise ValueError("Missing or oversized native source evidence")
    return source
