from __future__ import annotations

import array
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid


def _info(pid):
    text = Path(f"/proc/{pid}/stat").read_text()
    fields = text[text.rindex(")") + 2:].split()
    return {"pid": int(pid), "ppid": int(fields[1]), "start": fields[19],
            "state": fields[0]}


def _same(identity):
    try:
        now = _info(identity["pid"])
        return now["start"] == identity["start"] and now["state"] != "Z"
    except (OSError, ValueError):
        return False


def _snapshot(pid):
    result = {"cmdline": "", "ancestor_pids": [], "ancestor_cmdlines": []}
    seen = set()
    for depth in range(17):
        if pid <= 0 or pid in seen:
            break
        seen.add(pid)
        try:
            info = _info(pid)
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(
                b"\0", b" ").decode(errors="replace").strip()[:4096]
        except OSError:
            break
        if depth:
            result["ancestor_pids"].append(pid)
            result["ancestor_cmdlines"].append(cmd)
        else:
            result["cmdline"] = cmd
        pid = info["ppid"]
    return result


class ProcessGroups:
    def __init__(self):
        self.groups = {}
        self.lock = threading.RLock()
        self.errors = []

    def scan(self, group):
        processes = {}
        for path in Path("/proc").iterdir():
            if path.name.isdigit():
                try:
                    row = _info(int(path.name))
                    processes[row["pid"]] = row
                except (OSError, ValueError):
                    pass
        members = group["members"]
        live = {pid for pid, row in members.items()
                if pid in processes and processes[pid]["start"] == row["start"]}
        while True:
            children = {pid for pid, row in processes.items()
                        if row["ppid"] in live and pid not in live}
            if not children:
                break
            for pid in children:
                members[pid] = processes[pid]
            live.update(children)

    def kill(self, key):
        group = self.groups.get(key)
        if group is None:
            return
        stopped = set()
        for _ in range(32):
            self.scan(group)
            pending = [(pid, row) for pid, row in group["members"].items()
                       if pid not in stopped and _same(row)]
            if not pending:
                break
            for pid, row in pending:
                try:
                    os.kill(pid, signal.SIGSTOP)
                    stopped.add(pid)
                    if not _same(row):
                        os.kill(pid, signal.SIGCONT)
                    else:
                        until = time.monotonic() + .1
                        while _same(row) and _info(pid)["state"] not in ("T", "t"):
                            if time.monotonic() >= until:
                                break
                            time.sleep(.001)
                except ProcessLookupError:
                    pass
        for pid, row in reversed(list(group["members"].items())):
            if pid in stopped and _same(row):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        del self.groups[key]

    def command(self, request, peer_socket=None):
        with self.lock:
            if self.errors:
                raise RuntimeError(self.errors[-1])
            action = request["action"]
            if action == "identify":
                if peer_socket is None:
                    raise ValueError("Peer socket FD required")
                pid, uid, _ = struct.unpack("3i", peer_socket.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != 10001 or pid <= 0:
                    raise PermissionError("Expected a visible sandbox agent PID")
                return {"identity": _info(pid), "snapshot": _snapshot(pid)}
            if action == "health":
                return {}
            identity = request["identity"]
            key = (identity["pid"], identity["start"])
            if action == "arm":
                timeout = request["timeout"]
                if not 0 < timeout <= 3600 or not _same(identity):
                    raise RuntimeError("Invalid deadline or solver process has exited")
                group = self.groups.setdefault(key, {
                    "members": {identity["pid"]: identity}, "calls": {}})
                group["calls"][request["call_id"]] = time.monotonic() + timeout
                self.scan(group)
            elif action == "complete":
                group = self.groups.get(key)
                if group:
                    group["calls"].pop(request["call_id"], None)
                    if not group["calls"]:
                        del self.groups[key]
            elif action == "kill":
                self.kill(key)
            else:
                raise ValueError("Unknown process control operation")
            return {}

    def tick(self):
        with self.lock:
            for key, group in list(self.groups.items()):
                self.scan(group)
                if any(deadline <= time.monotonic() for deadline in group["calls"].values()):
                    self.kill(key)


def serve(path, owner_uid):
    path = Path(path)
    path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    os.chown(path, owner_uid, -1)
    path.chmod(0o600)
    server.listen(32)
    server.settimeout(.1)
    groups = ProcessGroups()
    while True:
        try:
            groups.tick()
        except Exception as exc:
            groups.errors.append(str(exc))
        try:
            connection, _ = server.accept()
        except socket.timeout:
            continue
        with connection:
            received = []
            peer = None
            try:
                connection.settimeout(5)
                _, uid, _ = struct.unpack("3i", connection.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != owner_uid:
                    raise PermissionError("Only the watchdog host may control processes")
                data, ancillary, flags, _ = connection.recvmsg(65536, socket.CMSG_SPACE(4))
                for level, kind, raw in ancillary:
                    if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                        fds = array.array("i")
                        fds.frombytes(raw[:len(raw) - len(raw) % fds.itemsize])
                        received.extend(fds)
                if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                    raise ValueError("Truncated process control request")
                while b"\n" not in data and len(data) < 65536:
                    chunk = connection.recv(65536 - len(data))
                    if not chunk:
                        break
                    data += chunk
                if received:
                    if len(received) != 1:
                        raise ValueError("Expected one peer socket")
                    peer = socket.socket(fileno=received.pop())
                result = groups.command(json.loads(data), peer)
                response = {"ok": True, **result}
            except Exception as exc:
                response = {"ok": False, "error": str(exc)}
            finally:
                if peer is not None:
                    peer.close()
                for fd in received:
                    os.close(fd)
            try:
                connection.sendall(json.dumps(response).encode() + b"\n")
            except OSError:
                pass


class DockerProcessController:
    def __init__(self, socket_dir):
        self.socket_dir = Path(socket_dir).resolve()
        self.socket_path = self.socket_dir / ("control-" + uuid.uuid4().hex[:12] + ".sock")
        self.helper_id = None
        self.lock = threading.Lock()
        self.container_id = None

    def start(self):
        with self.lock:
            if self.helper_id:
                return
            ids = subprocess.check_output(["docker", "ps", "-q", "--no-trunc"],
                                          text=True, timeout=10).split()
            if not ids:
                raise RuntimeError("No Docker sandbox for process control")
            rows = json.loads(subprocess.check_output(["docker", "inspect", *ids],
                                                     text=True, timeout=10))
            matches = [row for row in rows if any(
                m.get("Source") == str(self.socket_dir) and m.get("Destination") == "/orle-bridge"
                for m in row["Mounts"])]
            if len(matches) != 1:
                raise RuntimeError(f"Expected one sandbox, found {len(matches)}")
            target = matches[0]
            self.container_id = target["Id"]
            self.helper_id = subprocess.check_output([
                "docker", "run", "-d", "--rm", "--user=0", "--network=none",
                "--pid=container:" + self.container_id,
                "--label", "orle.solver-process-controller=" + self.container_id,
                "-v", str(self.socket_dir) + ":/control",
                "-v", str(Path(__file__).resolve()) + ":/controller.py:ro",
                "--entrypoint", "python", target["Image"], "-S", "/controller.py",
                "/control/" + self.socket_path.name, str(os.getuid()),
            ], text=True, timeout=20).strip()
            deadline = time.monotonic() + 5
            while not self.socket_path.exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("Process controller did not create its socket")
                time.sleep(.05)
            self.rpc({"action": "health"})

    def rpc(self, request, peer=None):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(5)
            connection.connect(str(self.socket_path))
            payload = json.dumps(request).encode() + b"\n"
            if peer is None:
                connection.sendall(payload)
            else:
                connection.sendmsg([payload], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                                 array.array("i", [peer.fileno()]))])
            response = b""
            while b"\n" not in response and len(response) < 65536:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                response += chunk
            result = json.loads(response)
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "Process controller failed"))
            return result

    def identify(self, peer):
        self.start()
        return self.rpc({"action": "identify"}, peer)

    def close(self):
        if self.helper_id:
            subprocess.run(["docker", "rm", "-f", self.helper_id],
                           capture_output=True, timeout=20, check=False)
        self.socket_path.unlink(missing_ok=True)


class DockerProcessGroup:
    def __init__(self, controller, identity):
        self.controller = controller
        self.identity = identity
        self.parent = Path("/docker") / controller.container_id
        self.path = self.parent / ("process-" + str(identity["pid"]) + "-" + identity["start"])

    def arm(self, call_id, timeout):
        self.controller.rpc({"action": "arm", "identity": self.identity,
                             "call_id": call_id, "timeout": timeout})

    def complete(self, call_id):
        self.controller.rpc({"action": "complete", "identity": self.identity,
                             "call_id": call_id})

    def kill(self):
        self.controller.rpc({"action": "kill", "identity": self.identity})

    def release(self):
        pass

    def reap(self):
        pass


if __name__ == "__main__":
    serve(sys.argv[1], int(sys.argv[2]))
