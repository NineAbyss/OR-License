#!/usr/local/bin/python -S
import base64
import json
import os
import socket
import sys

if len(sys.argv) != 2:
    print('Expected one complete shell invocation', file=sys.stderr)
    sys.exit(125)
keys = ('PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'TMPDIR', 'SHELL',
        'CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_TMPDIR')
request = {'command': sys.argv[1], 'cwd': os.getcwd(),
           'env': {k: os.environ[k] for k in keys if k in os.environ}}
try:
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(10)
        connection.connect('/isolation-ipc/shell.sock')
        connection.sendall(json.dumps(request).encode() + b'\n')
        connection.settimeout(None)
        with connection.makefile('rb') as stream:
            for line in stream:
                row = json.loads(line)
                if row['type'] == 'exit':
                    sys.exit(row['code'])
                target = sys.stdout.buffer if row['type'] == 'stdout' else sys.stderr.buffer
                target.write(base64.b64decode(row['data']))
                target.flush()
    print('Worker connection ended without an exit status', file=sys.stderr)
except (OSError, ValueError) as exc:
    print('Worker transport failure: ' + type(exc).__name__, file=sys.stderr)
sys.exit(125)
