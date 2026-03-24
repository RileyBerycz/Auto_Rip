from __future__ import annotations

import argparse

from dvdflix_core import RipPipeline, Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one DVDFlix rip pipeline cycle for a single drive.")
    parser.add_argument("--drive", required=True, help="Drive path, e.g. /dev/sr1")
    args = parser.parse_args()

    pipeline = RipPipeline(Settings())
    job = pipeline.run_for_drive(args.drive)
    print(job.to_dict())


if __name__ == "__main__":
    main()
