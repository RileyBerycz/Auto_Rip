from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def encode_file(src: Path, dst: Path) -> tuple[bool, str]:
    cmd = [
        "HandBrakeCLI",
        "-i",
        str(src),
        "-o",
        str(dst),
        "-e",
        "x265",
        "-q",
        "22",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip()
    return True, "encoded"


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch encode MKV library with x265 RF22.")
    parser.add_argument("--root", required=True, help="Library root path")
    parser.add_argument("--suffix", default=".x265.mkv", help="Output suffix")
    args = parser.parse_args()

    root = Path(args.root)
    for mkv in root.rglob("*.mkv"):
        if mkv.name.endswith(args.suffix):
            continue
        out = mkv.with_name(mkv.stem + args.suffix)
        ok, msg = encode_file(mkv, out)
        print(f"{mkv} -> {out}: {'OK' if ok else 'FAIL'} {msg}")


if __name__ == "__main__":
    main()
