from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

api_bp = Blueprint("api", __name__)


def _manager():
    return current_app.extensions["job_manager"]


@api_bp.get("/health")
def health() -> tuple:
    manager = _manager()
    return jsonify(
        {
            "ok": True,
            "drives": manager.settings.drives,
            "movies_path": str(manager.settings.movies_path),
            "tv_path": str(manager.settings.tv_path),
        }
    ), 200


@api_bp.get("/jobs")
def jobs() -> tuple:
    return jsonify({"jobs": _manager().list_jobs()}), 200


@api_bp.post("/jobs/start")
def start_job() -> tuple:
    payload = request.get_json(silent=True) or {}
    drive = payload.get("drive")
    if not drive:
        return jsonify({"ok": False, "error": "drive is required"}), 400

    result = _manager().start_job(drive)
    status = 200 if result.get("ok") else 409
    return jsonify(result), status


@api_bp.post("/jobs/start-all")
def start_all() -> tuple:
    return jsonify(_manager().start_all()), 200


@api_bp.get("/library")
def library() -> tuple:
    manager = _manager()

    def scan(root: Path) -> list[str]:
        if not root.exists():
            return []
        return sorted(str(p.relative_to(root)) for p in root.rglob("*.mkv"))

    return (
        jsonify(
            {
                "movies": scan(manager.settings.movies_path),
                "tvshows": scan(manager.settings.tv_path),
            }
        ),
        200,
    )
