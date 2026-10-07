#!/usr/local/bin/python -S
import base64
import errno
import json
import os
import selectors
import signal
import socket
import subprocess
import time

selector = selectors.DefaultSelector()
jobs = {}
shutdown = False
audit = open('/isolation-ipc/worker_events.jsonl', 'a', buffering=1)


def event(kind, **fields):
    audit.write(json.dumps({'time': time.time(), 'event': kind, **fields}) + '\n')


def send(job, row):
    job['out'].extend(json.dumps(row).encode() + b'\n')
    selector.modify(job['socket'], selectors.EVENT_READ | selectors.EVENT_WRITE, ('client', job))


def output(job, kind, data):
    send(job, {'type': kind, 'data': base64.b64encode(data).decode()})


def kill_group(job, reason):
    proc = job.get('proc')
    if proc is not None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        event('cancel', pid=proc.pid, reason=reason)


def close_job(job, cancel=False):
    if cancel:
        kill_group(job, 'client_disconnected')
    for pipe in list(job['pipes']):
        selector.unregister(pipe)
        pipe.close()
    job['pipes'].clear()
    selector.unregister(job['socket'])
    job['socket'].close()
    jobs.pop(job['id'], None)


def start(job, raw):
    try:
        request = json.loads(raw)
        command = request['command']
        cwd = request['cwd']
        if not isinstance(command, str) or not isinstance(cwd, str):
            raise ValueError('invalid command or cwd')
        env = dict(os.environ)
        allowed = {'PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'TMPDIR', 'SHELL',
                   'CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_TMPDIR'}
        env.update({k: v for k, v in request.get('env', {}).items()
                    if k in allowed and isinstance(v, str)})
        env.pop('CLAUDE_CODE_SHELL_PREFIX', None)
        proc = subprocess.Popen(['/bin/bash', '-c', command], cwd=cwd, env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
        job['proc'] = proc
        for kind, pipe in [('stdout', proc.stdout), ('stderr', proc.stderr)]:
            os.set_blocking(pipe.fileno(), False)
            job['pipes'].add(pipe)
            selector.register(pipe, selectors.EVENT_READ, (kind, job))
        event('start', pid=proc.pid, cwd=cwd, command_bytes=len(command.encode()))
    except (OSError, ValueError, KeyError) as exc:
        event('spawn_failed', error=type(exc).__name__, errno=getattr(exc, 'errno', None))
        output(job, 'stderr', ('Worker could not start command: ' + str(exc) + '\n').encode())
        send(job, {'type': 'exit', 'code': 125})
        job['done'] = True


def stop(signum, frame):
    global shutdown
    shutdown = True


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
server = socket.socket(socket.AF_UNIX)
socket_path = '/isolation-ipc/shell.sock'
try:
    os.unlink(socket_path)
except FileNotFoundError:
    pass
server.bind(socket_path)
os.chmod(socket_path, 0o660)
server.listen(16)
server.setblocking(False)
selector.register(server, selectors.EVENT_READ, ('server', None))
event('ready', pid=os.getpid())
try:
    while not shutdown:
        for key, mask in selector.select(.1):
            kind, job = key.data
            if kind == 'server':
                client, _ = server.accept()
                client.setblocking(False)
                if len(jobs) >= 16:
                    client.close()
                    continue
                job = {'id': client.fileno(), 'socket': client, 'in': bytearray(),
                       'out': bytearray(), 'pipes': set(), 'proc': None,
                       'done': False, 'requested': False, 'created': time.monotonic()}
                jobs[job['id']] = job
                selector.register(client, selectors.EVENT_READ, ('client', job))
            elif job['id'] not in jobs:
                continue
            elif kind == 'client':
                try:
                    if mask & selectors.EVENT_READ:
                        chunk = key.fileobj.recv(65536)
                        if not chunk:
                            close_job(job, cancel=not job['done'])
                            continue
                        if not job['requested']:
                            job['in'].extend(chunk)
                            if len(job['in']) > 1024 * 1024:
                                close_job(job, cancel=True)
                                continue
                            if b'\n' in job['in']:
                                job['requested'] = True
                                start(job, bytes(job['in']).split(b'\n', 1)[0])
                    if mask & selectors.EVENT_WRITE and job['out']:
                        count = key.fileobj.send(job['out'])
                        del job['out'][:count]
                    if not job['out']:
                        if job['done']:
                            close_job(job)
                        else:
                            selector.modify(key.fileobj, selectors.EVENT_READ, ('client', job))
                except (BrokenPipeError, ConnectionResetError):
                    close_job(job, cancel=not job['done'])
                except BlockingIOError:
                    pass
            else:
                if len(job['out']) > 1024 * 1024:
                    continue
                data = os.read(key.fd, 16384)
                if data:
                    output(job, kind, data)
                else:
                    selector.unregister(key.fileobj)
                    job['pipes'].remove(key.fileobj)
                    key.fileobj.close()
        for job in list(jobs.values()):
            proc = job['proc']
            if time.monotonic() - job['created'] > float(os.environ.get('ORLE_ISOLATION_COMMAND_TIMEOUT_SECONDS', '43200')):
                kill_group(job, 'deadline')
                if proc is None:
                    close_job(job)
                    continue
            if proc is not None and proc.poll() is not None and not job['pipes'] and not job['done']:
                code = proc.returncode if proc.returncode >= 0 else 128 - proc.returncode
                event('exit', pid=proc.pid, code=code)
                send(job, {'type': 'exit', 'code': code})
                job['done'] = True
        active = {job['proc'].pid for job in jobs.values() if job['proc'] is not None}
        try:
            while True:
                child = os.waitid(os.P_ALL, 0, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if child is None or child.si_pid in active:
                    break
                os.waitpid(child.si_pid, os.WNOHANG)
        except ChildProcessError:
            pass
finally:
    for job in list(jobs.values()):
        close_job(job, cancel=True)
    server.close()
    event('stopped')
