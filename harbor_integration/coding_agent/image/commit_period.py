#!/usr/local/bin/python
import argparse
import base64
import json
import socket
import sys


def main():
    parser = argparse.ArgumentParser(description='Permanently lock the current rolling submission.')
    parser.add_argument('plan_file')
    args = parser.parse_args()
    try:
        with open(args.plan_file, 'rb') as f:
            raw = f.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError('Plan file too large')
        request = {'payload_b64': base64.b64encode(raw).decode('ascii')}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(300)
            sock.connect('/orle-bridge/rolling.sock')
            sock.sendall(json.dumps(request, allow_nan=False).encode() + b'\n')
            response = json.loads(sock.makefile('rb').readline(1048576))
        print(json.dumps(response, ensure_ascii=False))
        return 1 if response.get('phase') in {'protocol_error', 'rejected'} else 0
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
