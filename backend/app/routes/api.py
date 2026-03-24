from __future__ import annotations

import shutil
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

api_bp = Blueprint("api", __name__)


def _manager():
    return current_app.extensions["job_manager"]


def _store():
    return current_app.extensions["state_store"]


def _auth_token() -> str:
    raw = request.headers.get("Authorization", "")
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return ""


def require_auth(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        store = _store()
        if not store.is_setup_complete():
            return jsonify({"ok": False, "error": "setup not complete"}), 428

        token = _auth_token()
        if not token or not store.validate_token(token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return func(*args, **kwargs)

    return wrapped


def _runtime_settings_payload(payload: dict) -> dict[str, str]:
    keys = [
        "MOVIES_PATH",
        "TV_PATH",
        "TEMP_RIP_PATH",
        "DRIVES",
        "TMDB_API_KEY",
        "OLLAMA_URL",
        "OLLAMA_MODEL",
        "RUNTIME_TOLERANCE_MINUTES",
        "MAX_IDENTIFY_WORKERS",
        "DISC_CACHE_DB",
    ]
    result: dict[str, str] = {}
    for key in keys:
        value = payload.get(key)
        if value is not None:
            result[key] = str(value)
    return result


def _runtime_setting_keys() -> list[str]:
    return [
        "MOVIES_PATH",
        "TV_PATH",
        "TEMP_RIP_PATH",
        "DRIVES",
        "TMDB_API_KEY",
        "OLLAMA_URL",
        "OLLAMA_MODEL",
        "RUNTIME_TOLERANCE_MINUTES",
        "MAX_IDENTIFY_WORKERS",
        "DISC_CACHE_DB",
    ]


def _profile_setting_keys() -> list[str]:
    return [
        "PROFILE_SERVER",
        "PROFILE_STORAGE_ROOT",
        "PROFILE_DRIVE_SR0",
        "PROFILE_DRIVE_SR1",
        "PROFILE_DRIVE_SR2",
        "PROFILE_GPU",
        "PROFILE_JELLYFIN_URL",
        "PROFILE_OLLAMA_MODEL",
        "PROFILE_NOTES",
    ]


def _profile_payload(payload: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in _profile_setting_keys():
        value = payload.get(key)
        if value is not None:
            result[key] = str(value)
    return result


@api_bp.get("/setup/status")
def setup_status() -> tuple:
    store = _store()
    configured = store.is_setup_complete()
    manager = _manager()
    return (
        jsonify(
            {
                "ok": True,
                "configured": configured,
                "settings": manager.settings.to_runtime_dict(),
            }
        ),
        200,
    )


@api_bp.post("/setup/initialize")
def setup_initialize() -> tuple:
    store = _store()
    if store.is_setup_complete():
        return jsonify({"ok": False, "error": "setup already complete"}), 409

    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()
    settings_updates = _runtime_settings_payload(payload.get("settings", {}))
    profile_updates = _profile_payload(payload.get("profile", {}))

    if not username or not password:
        return jsonify({"ok": False, "error": "username and password are required"}), 400

    try:
        store.create_admin(username, password)
        store.upsert_settings(settings_updates)
        store.upsert_settings(profile_updates)
        _manager().reconfigure(store.get_settings(_runtime_setting_keys()))
        token = store.login(username, password)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "token": token}), 201


@api_bp.post("/auth/login")
def login() -> tuple:
    store = _store()
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()
    token = store.login(username, password)
    if not token:
        return jsonify({"ok": False, "error": "invalid credentials"}), 401
    return jsonify({"ok": True, "token": token}), 200


@api_bp.get("/settings")
@require_auth
def settings_get() -> tuple:
    manager = _manager()
    return jsonify({"ok": True, "settings": manager.settings.to_runtime_dict()}), 200


@api_bp.post("/settings")
@require_auth
def settings_set() -> tuple:
    payload = request.get_json(silent=True) or {}
    updates = _runtime_settings_payload(payload)
    _store().upsert_settings(updates)
    _manager().reconfigure(_store().get_settings(_runtime_setting_keys()))
    return jsonify({"ok": True}), 200


@api_bp.get("/profile")
@require_auth
def profile_get() -> tuple:
    values = _store().get_settings(_profile_setting_keys())
    return jsonify({"ok": True, "profile": values}), 200


@api_bp.post("/profile")
@require_auth
def profile_set() -> tuple:
    payload = request.get_json(silent=True) or {}
    updates = _profile_payload(payload)
    _store().upsert_settings(updates)
    return jsonify({"ok": True}), 200


@api_bp.get("/capabilities")
@require_auth
def capabilities() -> tuple:
    manager = _manager()
    settings = manager.settings

    tools = {
        "lsdvd": bool(shutil.which("lsdvd")),
        "makemkvcon": bool(shutil.which("makemkvcon")),
        "eject": bool(shutil.which("eject")),
    }
    drive_status = {drive: Path(drive).exists() for drive in settings.drives}

    movies_ok = settings.movies_path.exists()
    tv_ok = settings.tv_path.exists()
    temp_ok = settings.temp_rip_path.exists()

    return (
        jsonify(
            {
                "ok": True,
                "tools": tools,
                "drives": drive_status,
                "paths": {
                    "movies": {"path": str(settings.movies_path), "exists": movies_ok},
                    "tv": {"path": str(settings.tv_path), "exists": tv_ok},
                    "temp": {"path": str(settings.temp_rip_path), "exists": temp_ok},
                },
            }
        ),
        200,
    )


@api_bp.get("/health")
@require_auth
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
@require_auth
def jobs() -> tuple:
    return jsonify({"jobs": _manager().list_jobs()}), 200


@api_bp.post("/jobs/start")
@require_auth
def start_job() -> tuple:
    payload = request.get_json(silent=True) or {}
    drive = payload.get("drive")
    if not drive:
        return jsonify({"ok": False, "error": "drive is required"}), 400

    result = _manager().start_job(drive)
    status = 200 if result.get("ok") else 409
    return jsonify(result), status


@api_bp.post("/jobs/start-all")
@require_auth
def start_all() -> tuple:
    return jsonify(_manager().start_all()), 200


@api_bp.get("/library")
@require_auth
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
