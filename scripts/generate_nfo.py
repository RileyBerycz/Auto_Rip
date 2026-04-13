from __future__ import annotations

import argparse
import os
from pathlib import Path

from dvdflix_core.nfo import create_nfo_for_library


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate movie.nfo or tvshow.nfo files for a media library.")
    parser.add_argument("--root", required=True, help="Library root path")
    parser.add_argument("--tmdb-key", default=os.getenv("TMDB_API_KEY", ""), help="TMDB API key")
    args = parser.parse_args()

    root = Path(args.root)
    generated = create_nfo_for_library(root, args.tmdb_key)
    print(f"Processed {root}; generated {generated} NFO file(s).")


if __name__ == "__main__":
    main()
