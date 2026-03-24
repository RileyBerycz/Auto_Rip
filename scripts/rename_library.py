from __future__ import annotations

import argparse
import re
from pathlib import Path


def clean_name(name: str) -> str:
    name = name.replace("_", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def rename_tree(root: Path) -> None:
    # Process deeper paths first to avoid invalidating child references.
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        new_name = clean_name(path.name)
        if new_name != path.name:
            target = path.with_name(new_name)
            if not target.exists():
                path.rename(target)
                print(f"Renamed: {path} -> {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize naming in media library.")
    parser.add_argument("--root", required=True, help="Library root path")
    args = parser.parse_args()

    rename_tree(Path(args.root))


if __name__ == "__main__":
    main()
