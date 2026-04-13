from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import requests


def clean_name(name: str) -> str:
    name = name.replace("_", " ").replace(".", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _ollama_suggest_name(current_name: str, file_samples: list[str], base_url: str, model: str) -> str | None:
    prompt = (
        "You are a folder renaming assistant for a movie or TV library. "
        "Given the current folder name and a few sample file names, suggest a cleaner folder name. "
        "Return only the suggested folder name, nothing else. "
        f"Current folder name: {current_name}. "
    )
    if file_samples:
        prompt += f"Sample files: {', '.join(file_samples[:5])}. "
    prompt += "If the current name is already clean, repeat it exactly."

    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=30,
        )
        response.raise_for_status()
        text = response.json().get("response", "").strip()
    except Exception:
        return None

    cleaned = text.splitlines()[0].strip()
    if cleaned:
        return cleaned
    return None


def rename_tree(root: Path) -> None:
    ollama_url = os.getenv("OLLAMA_URL", "").strip()
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b").strip()
    use_llm = bool(ollama_url)

    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        current_name = path.name
        target_name = clean_name(current_name)

        if use_llm and path.is_dir() and ("_" in current_name or "." in current_name or current_name.lower() != current_name):
            sample_files = []
            try:
                sample_files = [str(child.name) for child in sorted(path.iterdir()) if child.is_file()][:5]
            except OSError:
                sample_files = []
            suggestion = _ollama_suggest_name(current_name, sample_files, ollama_url, ollama_model)
            if suggestion and suggestion != current_name:
                target_name = clean_name(suggestion)

        if target_name != current_name:
            target = path.with_name(target_name)
            if not target.exists():
                try:
                    path.rename(target)
                    print(f"Renamed: {path} -> {target}")
                except OSError as exc:
                    print(f"Skipped rename {path}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize naming in media library.")
    parser.add_argument("--root", required=True, help="Library root path")
    args = parser.parse_args()

    rename_tree(Path(args.root))


if __name__ == "__main__":
    main()
