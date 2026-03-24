from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Test subtitle extraction/OCR fallback flow.")
    parser.add_argument("--mkv", required=True, help="Path to ripped MKV")
    parser.add_argument("--out", default="~/dvdflix_subtest", help="Output directory")
    args = parser.parse_args()

    mkv_path = Path(args.mkv).expanduser()
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    sub_idx = out_dir / "disc_subs.idx"
    cmd_extract = ["mkvextract", "tracks", str(mkv_path), f"2:{sub_idx}"]
    proc_extract = subprocess.run(cmd_extract, capture_output=True, text=True, check=False)
    print("mkvextract rc:", proc_extract.returncode)
    print(proc_extract.stdout)
    print(proc_extract.stderr)

    cmd_ocr = ["vobsub2srt", str(sub_idx)]
    proc_ocr = subprocess.run(cmd_ocr, capture_output=True, text=True, check=False)
    print("vobsub2srt rc:", proc_ocr.returncode)
    print(proc_ocr.stdout)
    print(proc_ocr.stderr)


if __name__ == "__main__":
    main()
