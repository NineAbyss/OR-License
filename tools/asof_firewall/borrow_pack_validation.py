
from __future__ import annotations

import csv
import gzip
from pathlib import Path


def validate_borrow_pack(pack: Path, days: list[str], manifest: dict) -> None:
    if (
        manifest.get("borrow_slips") != "borrow_slips/<date>.csv"
        or manifest.get("borrow_slip_index") != "borrow_slips/index.csv.gz"
        or manifest.get("borrow_slip_index_through") != days[-1]
    ):
        raise ValueError("borrow slip manifest is missing or stale")

    root = pack / "borrow_slips"
    if root.is_symlink() or not root.is_dir():
        raise ValueError("borrow slips directory is missing or is a symlink")
    expected_files = {f"{day}.csv" for day in days} | {"index.csv.gz"}
    files = list(root.iterdir())
    if {path.name for path in files} != expected_files or any(
        path.is_symlink() or not path.is_file() for path in files
    ):
        raise ValueError("borrow slips have missing days or unexpected files")

    for day in days:
        try:
            with (root / f"{day}.csv").open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames != [
                    "id", "instrument", "available", "apply_rate", "cre_time"
                ]:
                    raise ValueError(f"borrow slips schema is invalid for {day}")
                if any(
                    not row["id"] or not row["instrument"] or row["cre_time"] != day
                    for row in reader
                ):
                    raise ValueError(f"borrow slips contain invalid rows for {day}")
        except (OSError, UnicodeError, csv.Error) as exc:
            raise ValueError(f"borrow slips are unreadable for {day}") from exc

    try:
        with gzip.open(root / "index.csv.gz", "rt", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["id", "instrument", "cre_time"]:
                raise ValueError("borrow slip index schema is invalid")
            count = 0
            for row in reader:
                if (
                    not row["id"] or not row["instrument"]
                    or not row["cre_time"] or row["cre_time"] > days[-1]
                ):
                    raise ValueError("borrow slip index contains invalid rows")
                count += 1
    except (OSError, UnicodeError, EOFError, csv.Error) as exc:
        raise ValueError("borrow slip index is unreadable") from exc
    if count != manifest.get("borrow_slip_index_rows"):
        raise ValueError("borrow slip index row count differs from manifest")
