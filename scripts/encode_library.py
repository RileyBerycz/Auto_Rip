from __future__ import annotations

import argparse
import os
from pathlib import Path

from dvdflix_core.encoder import encode_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch encode MKV library with HandBrakeCLI.")
    parser.add_argument("--root", required=True, help="Library root path")
    parser.add_argument("--suffix", default=".x265.mkv", help="Output suffix")
    parser.add_argument("--preset", default=None, help="HandBrake preset to use")
    args = parser.parse_args()

    root = Path(args.root)
    preset = args.preset or os.getenv("HANDBRAKE_PRESET", "default")
    for mkv in root.rglob("*.mkv"):
        if mkv.name.endswith(args.suffix):
            continue
        out = mkv.with_name(mkv.stem + args.suffix)
        ok, msg = encode_file(mkv, out, preset=preset)
        print(f"{mkv} -> {out}: {'OK' if ok else 'FAIL'} {msg}")


if __name__ == "__main__":
    main()
