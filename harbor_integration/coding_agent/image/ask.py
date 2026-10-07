#!/usr/local/bin/python
import argparse
import json
import socket
import sys


def main():
    parser = argparse.ArgumentParser(description="Contact the business respondent.")
    parser.add_argument("question", help="One business question, quoted as one argument.")
    args = parser.parse_args()
    if not args.question.strip() or len(args.question.encode()) > 16384:
        parser.error("Question must contain between 1 and 16384 UTF-8 bytes.")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1750)
            sock.connect("/orle-bridge/ask.sock")
            sock.sendall(json.dumps({"query": args.question}).encode() + b"\n")
            response = sock.makefile("rb").readline(1048577)
        if len(response) > 1048576:
            raise ValueError("response too large")
        payload = json.loads(response)
        print(payload["answer"], file=sys.stdout if payload["ok"] else sys.stderr)
        return 0 if payload["ok"] else 1
    except (OSError, ValueError, KeyError):
        print("The business information service is unavailable.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
