#!/usr/bin/env python3
"""A tiny, deterministic workload.

This is *your* code -- caasi does not care what it does. It reads a small CSV,
writes a summary, and exits 0. Everything around it (the project, the workload
declaration, the run tracking, the artifact routing) is what caasi provides.
"""
from __future__ import annotations

import csv
import pathlib
import sys

SAMPLES = [
    ("t", "value"),
    ("0.0", "1.0"),
    ("0.1", "1.4"),
    ("0.2", "1.9"),
    ("0.3", "2.2"),
]


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent.parent
    data = here / "data.csv"
    with data.open("w", newline="") as fh:
        csv.writer(fh).writerows(SAMPLES)

    rows = list(csv.reader(data.open()))[1:]
    values = [float(r[1]) for r in rows]
    summary = sum(values) / len(values)

    out = here / "mean.out"
    out.write_text(f"mean={summary:.3f}\n", encoding="utf-8")
    print(f"[demo] read {len(values)} rows -> {out.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
