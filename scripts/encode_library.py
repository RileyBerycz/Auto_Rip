from __future__ import annotations

import argparse
import os
from pathlib import Path

from dvdflix_core.encoder import encode_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch encode MKV library with HandBrakeCLI.")
    parser.add_argument("--root", help="Library root path")
    parser.add_argument("--path", help="Specific file or directory to encode")
    parser.add_argument("--suffix", default=".x265.mkv", help="Output suffix")
    parser.add_argument("--preset", default=None, help="HandBrake preset to use")
    args = parser.parse_args()

    if not args.root and not args.path:
        parser.error("Either --root or --path must be provided")

    preset = args.preset or os.getenv("HANDBRAKE_PRESET", "default")
    candidates: list[Path] = []
    if args.path:
        target = Path(args.path)
        if not target.exists():
            print(f"Path not found: {target}")
            return
        if target.is_file():
            candidates = [target]
        else:
            candidates = sorted([p for p in target.rglob("*.mkv") if not p.name.endswith(args.suffix)])
    else:
        root = Path(args.root)
        if not root.exists():
            print(f"Root not found: {root}")
            return
        candidates = sorted([p for p in root.rglob("*.mkv") if not p.name.endswith(args.suffix)])

    if not candidates:
        print("No MKV files found to encode.")
        return

    for mkv in candidates:
        out = mkv.with_name(mkv.stem + args.suffix)
        ok, msg = encode_file(mkv, out, preset=preset)
        print(f"{mkv} -> {out}: {'OK' if ok else 'FAIL'} {msg}")


if __name__ == "__main__":
    main()
