from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/asof_firewall"))
from harbor_score import score_output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--windows", nargs="+", default=["evaluation"])
    args = parser.parse_args()
    result = score_output(Path(args.output), Path(args.work_root),
                          contract=args.contract, windows=tuple(args.windows))
    print("ORLE_ASOF_JUDGMENT=" + json.dumps(result, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
