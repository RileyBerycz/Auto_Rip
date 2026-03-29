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
        "OMDB_API_KEY",
        "TVDB_API_KEY",
        "TVDB_PIN",
        "OLLAMA_URL",
        "OLLAMA_MODEL",
        "RUNTIME_TOLERANCE_MINUTES",
        "IDENTIFY_MIN_CONFIDENCE",
        "MAX_IDENTIFY_WORKERS",
        "DISC_CACHE_DB",
        "OPENSUBTITLES_API_KEY",
        "ENABLE_WEB_SEARCH",
        "SEARXNG_URL",
        "HANDBRAKE_PRESET",
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
        "OMDB_API_KEY",
        "TVDB_API_KEY",
        "TVDB_PIN",
        "OLLAMA_URL",
        "OLLAMA_MODEL",
        "RUNTIME_TOLERANCE_MINUTES",
        "IDENTIFY_MIN_CONFIDENCE",
        "MAX_IDENTIFY_WORKERS",
        "DISC_CACHE_DB",
        "OPENSUBTITLES_API_KEY",
        "ENABLE_WEB_SEARCH",
        "SEARXNG_URL",
        "HANDBRAKE_PRESET",
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

    issues: list[str] = []
    if not tools["makemkvcon"]:
        issues.append("makemkvcon is missing in backend container/runtime")
    if not any(drive_status.values()):
        issues.append("No optical drives are visible inside backend container")
    if not movies_ok:
        issues.append(f"Movies path not found: {settings.movies_path}")
    if not tv_ok:
        issues.append(f"TV path not found: {settings.tv_path}")
    if not temp_ok:
        issues.append(f"Temp rip path not found: {settings.temp_rip_path}")

    hints = [
        "Use docker-compose.ripper.yml in Dockge for /dev/sr* device mappings and host media mounts.",
        "Set DRIVES in app settings to comma-separated /dev/sr* values matching mapped devices.",
        "If makemkvcon is host-only, run ripping via host auto_rip.py or provide makemkvcon inside backend runtime.",
    ]

    ripper_ready = (
        tools["lsdvd"]
        and tools["makemkvcon"]
        and any(drive_status.values())
        and movies_ok
        and tv_ok
        and temp_ok
    )

    return (
        jsonify(
            {
                "ok": True,
                "ripper_ready": ripper_ready,
                "tools": tools,
                "drives": drive_status,
                "issues": issues,
                "hints": hints,
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


@api_bp.post("/jobs/<job_id>/override-title")
@require_auth
def override_job_title(job_id: str) -> tuple:
    """
    Manually override the title for a job.
    Payload: { "title": "New Title", "year": "2024", "media_type": "movie|tv" }
    """
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()
    year = str(payload.get("year", "")).strip()
    media_type = str(payload.get("media_type", "movie")).strip()
    
    if not title:
        return jsonify({"ok": False, "error": "title is required"}), 400
    
    job = _manager().get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404
    
    # Update in-memory job metadata for active dashboard visibility.
    _manager().update_job(
        job_id,
        {
            "title": title,
            "media_type": media_type,
        },
    )
    return jsonify({"ok": True}), 200


@api_bp.post("/search/tmdb")
@require_auth
def search_tmdb() -> tuple:
    """
    Search TMDB for titles to help with manual overrides.
    Payload: { "query": "The Matrix", "media_type": "movie|tv" }
    """
    from dvdflix_core.clients import TMDBClient
    
    payload = request.get_json(silent=True) or {}
    query = str(payload.get("query", "")).strip()
    media_type = str(payload.get("media_type", "movie")).strip()
    
    if not query:
        return jsonify({"ok": False, "error": "query is required"}), 400
    
    manager = _manager()
    tmdb = TMDBClient(api_key=manager.settings.tmdb_api_key)
    
    try:
        results = tmdb.search(query, media_type)
        return jsonify({"ok": True, "results": results}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api_bp.get("/history")
@require_auth
def history() -> tuple:
    raw_limit = request.args.get("limit", "500")
    try:
        limit = max(1, min(5000, int(raw_limit)))
    except ValueError:
        limit = 500

    items = _manager().list_history(limit=limit)
    return jsonify({"ok": True, "history": items}), 200


@api_bp.post("/history/<disc_hash>")
@require_auth
def update_history(disc_hash: str) -> tuple:
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()
    year = str(payload.get("year", "")).strip()
    media_type = str(payload.get("media_type", "movie")).strip().lower()
    notes = str(payload.get("notes", "")).strip()

    if not title:
        return jsonify({"ok": False, "error": "title is required"}), 400
    if media_type not in {"movie", "tv"}:
        return jsonify({"ok": False, "error": "media_type must be movie or tv"}), 400

    ok = _manager().update_history(
        disc_hash,
        title=title,
        year=year,
        media_type=media_type,
        notes=notes,
    )
    if not ok:
        return jsonify({"ok": False, "error": "history record not found"}), 404
    return jsonify({"ok": True}), 200
