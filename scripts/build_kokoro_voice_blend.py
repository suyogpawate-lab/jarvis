#!/usr/bin/env python3
"""Create a Kokoro style-vector blend: 70% masculine am_onyx + 30% af_nicole."""
from __future__ import annotations
import argparse
import math
import struct
from pathlib import Path

FRAME_FLOATS = 256
CHUNK_FLOATS = 4096

def blend(base: Path, donor: Path, output: Path, donor_weight: float = 0.30) -> int:
    if not 0.0 <= donor_weight <= 1.0:
        raise ValueError("donor_weight must be between 0 and 1")
    if not base.is_file() or not donor.is_file():
        raise FileNotFoundError("Both source Kokoro voice packs must exist.")
    if base.stat().st_size != donor.stat().st_size:
        raise ValueError("Voice packs have different sizes; they cannot be blended safely.")
    size = base.stat().st_size
    if size == 0 or size % (FRAME_FLOATS * 4):
        raise ValueError(f"Unexpected raw voice-pack size: {size}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".part")
    try:
        with base.open("rb") as a, donor.open("rb") as b, temp.open("wb") as out:
            remaining = size // 4
            while remaining:
                count = min(CHUNK_FLOATS, remaining)
                raw_a, raw_b = a.read(count * 4), b.read(count * 4)
                va = struct.unpack("<" + "f" * count, raw_a)
                vb = struct.unpack("<" + "f" * count, raw_b)
                mixed = []
                for x, y in zip(va, vb):
                    value = (1.0 - donor_weight) * x + donor_weight * y
                    if not math.isfinite(value):
                        raise ValueError("Non-finite value found in source voice embedding.")
                    mixed.append(value)
                out.write(struct.pack("<" + "f" * count, *mixed))
                remaining -= count
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)
    return size

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", type=Path, required=True)
    parser.add_argument("--base", default="am_onyx")
    parser.add_argument("--donor", default="af_nicole")
    parser.add_argument("--weight", type=float, default=0.30)
    parser.add_argument("--output", default="jarvis_nicole30")
    args = parser.parse_args()
    size = blend(args.voices / f"{args.base}.bin", args.voices / f"{args.donor}.bin",
                 args.voices / f"{args.output}.bin", args.weight)
    print(f"Created {args.output}.bin: {(1-args.weight):.0%} {args.base} + {args.weight:.0%} {args.donor} ({size:,} bytes)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
