from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from dvdflix_core.config import discover_optical_drives
from dvdflix_core.ripper import eject_drive

api_bp = Blueprint("api", __name__)

_task_executor = ThreadPoolExecutor(max_workers=1)
_task_lock = threading.Lock()
_tasks: dict[str, dict] = {}
_task_procs: dict[str, subprocess.Popen] = {}


def _tool_exists(tool_cmd: str) -> bool:
    if not tool_cmd:
        return False
    if "/" in tool_cmd:
        return Path(tool_cmd).exists()
    return bool(shutil.which(tool_cmd))


def _manager():
    return current_app.extensions["job_manager"]


def _append_task_log(task: dict, message: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    task.setdefault("logs", []).append(f"[{ts}] {message}")
    if len(task["logs"]) > 500:
        task["logs"] = task["logs"][-500:]


def _create_task(kind: str, command: list[str]) -> dict:
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "kind": kind,
        "state": "queued",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "command": command,
        "logs": [],
    }
    with _task_lock:
        _tasks[task_id] = task
    return task


def _run_task(task_id: str) -> None:
    with _task_lock:
        task = _tasks.get(task_id)
        if not task:
            return
        if task.get("state") == "canceled":
            return
        task["state"] = "running"
        task["updated_at"] = datetime.utcnow().isoformat() + "Z"
        _append_task_log(task, "Task started")
        cmd = list(task.get("command", []))

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        with _task_lock:
            _task_procs[task_id] = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            with _task_lock:
                task = _tasks.get(task_id)
                if not task:
                    continue
                _append_task_log(task, line)
                task["updated_at"] = datetime.utcnow().isoformat() + "Z"

        rc = proc.wait()
        with _task_lock:
            task = _tasks.get(task_id)
            if task:
                task["state"] = "complete" if rc == 0 else "failed"
                task["return_code"] = rc
                task["updated_at"] = datetime.utcnow().isoformat() + "Z"
                _append_task_log(task, f"Task finished with code {rc}")
            _task_procs.pop(task_id, None)
    except Exception as exc:  # noqa: BLE001
        with _task_lock:
            task = _tasks.get(task_id)
            if task:
                task["state"] = "failed"
                task["updated_at"] = datetime.utcnow().isoformat() + "Z"
                _append_task_log(task, f"Task crashed: {exc}")
            _task_procs.pop(task_id, None)


def _store():
    return current_app.extensions["state_store"]


def _auth_token() -> str:
    raw = request.headers.get("Authorization", "")
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return ""


def _current_user() -> dict | None:
    token = _auth_token()
    if not token:
        return None
    return _store().get_user_by_token(token)


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
        "MAKEMKVCON_PATH",
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
        "MAKEMKVCON_PATH",
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


def _list_temp_entries(root: Path, limit: int = 500) -> list[dict]:
    if not root.exists():
        return []

    entries: list[dict] = []
    for p in sorted(root.rglob("*")):
        if len(entries) >= limit:
            break
        try:
            rel = str(p.relative_to(root))
            stat = p.stat()
            entries.append(
                {
                    "path": rel,
                    "is_dir": p.is_dir(),
                    "size": 0 if p.is_dir() else int(stat.st_size),
                    "modified": int(stat.st_mtime),
                }
            )
        except OSError:
            continue
    return entries


@api_bp.get("/setup/status")
def setup_status() -> tuple:
    store = _store()
    configured = store.is_setup_complete()
    manager = _manager()
    detected_drives = discover_optical_drives()
    return (
        jsonify(
            {
                "ok": True,
                "configured": configured,
                "settings": manager.settings.to_runtime_dict(),
                "detected_drives": detected_drives,
            }
        ),
        200,
    )


@api_bp.get("/setup/detected-drives")
def setup_detected_drives() -> tuple:
    drives = discover_optical_drives()
    return jsonify({"ok": True, "drives": drives, "csv": ",".join(drives)}), 200


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


@api_bp.get("/accounts")
@require_auth
def accounts_list() -> tuple:
    user = _current_user()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    users = _store().list_users()
    return jsonify({"ok": True, "users": users, "current_user": user}), 200


@api_bp.post("/accounts")
@require_auth
def accounts_create() -> tuple:
    actor = _current_user()
    if not actor:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not actor.get("is_admin"):
        return jsonify({"ok": False, "error": "admin required"}), 403

    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()
    is_admin = bool(payload.get("is_admin", False))

    try:
        _store().create_user(username, password, is_admin=is_admin)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 409

    return jsonify({"ok": True}), 201


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
        "makemkvcon": _tool_exists(settings.makemkvcon_path),
        "eject": bool(shutil.which("eject")),
    }
    drive_status = {drive: Path(drive).exists() for drive in settings.drives}

    movies_ok = settings.movies_path.exists()
    tv_ok = settings.tv_path.exists()
    temp_ok = settings.temp_rip_path.exists()

    issues: list[str] = []
    if not tools["makemkvcon"]:
        issues.append(f"makemkvcon is missing in backend container/runtime ({settings.makemkvcon_path})")
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


@api_bp.get("/drives/status")
@require_auth
def drives_status() -> tuple:
    statuses = _manager().list_drive_statuses()
    total = len(statuses)
    with_disc = sum(1 for d in statuses if d.get("has_disc"))
    readable = sum(1 for d in statuses if d.get("readable"))
    empty = sum(1 for d in statuses if d.get("status") == "empty")
    return (
        jsonify(
            {
                "ok": True,
                "drives": statuses,
                "summary": {
                    "total": total,
                    "with_disc": with_disc,
                    "readable": readable,
                    "empty": empty,
                },
            }
        ),
        200,
    )


@api_bp.post("/drives/eject")
@require_auth
def drives_eject() -> tuple:
    payload = request.get_json(silent=True) or {}
    drive = str(payload.get("drive", "")).strip()
    if not drive:
        return jsonify({"ok": False, "error": "drive is required"}), 400

    ok, message = eject_drive(drive)
    code = 200 if ok else 409
    return jsonify({"ok": ok, "drive": drive, "message": message}), code


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


@api_bp.post("/jobs/<job_id>/cancel")
@require_auth
def cancel_job(job_id: str) -> tuple:
    result = _manager().cancel_job(job_id)
    code = 200 if result.get("ok") else 404
    return jsonify(result), code


@api_bp.post("/jobs/<job_id>/cleanup-output")
@require_auth
def cleanup_job_output(job_id: str) -> tuple:
    result = _manager().cleanup_job_output(job_id)
    code = 200 if result.get("ok") else 409
    return jsonify(result), code


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


@api_bp.get("/temp-files")
@require_auth
def temp_files() -> tuple:
    manager = _manager()
    root = manager.settings.temp_rip_path
    entries = _list_temp_entries(root)
    files = [e for e in entries if not e.get("is_dir")]
    total_bytes = sum(int(e.get("size", 0)) for e in files)
    return (
        jsonify(
            {
                "ok": True,
                "root": str(root),
                "exists": root.exists(),
                "entries": entries,
                "summary": {
                    "count": len(entries),
                    "file_count": len(files),
                    "total_bytes": total_bytes,
                },
            }
        ),
        200,
    )


@api_bp.post("/temp-files/cleanup")
@require_auth
def temp_files_cleanup() -> tuple:
    manager = _manager()
    root = manager.settings.temp_rip_path
    if not root.exists():
        return jsonify({"ok": True, "removed": 0, "message": "Temp path does not exist"}), 200

    removed = 0
    errors: list[str] = []

    # Delete files first, then directories deepest-first.
    for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        try:
            if p.is_file() or p.is_symlink():
                p.unlink(missing_ok=True)
                removed += 1
            elif p.is_dir():
                p.rmdir()
                removed += 1
        except OSError as exc:
            errors.append(f"{p}: {exc}")

    return jsonify({"ok": len(errors) == 0, "removed": removed, "errors": errors}), 200


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


@api_bp.get("/maintenance/tasks")
@require_auth
def maintenance_tasks() -> tuple:
    with _task_lock:
        ordered = sorted(_tasks.values(), key=lambda x: x.get("updated_at", ""), reverse=True)
    return jsonify({"ok": True, "tasks": ordered[:50]}), 200


@api_bp.post("/maintenance/encode-library")
@require_auth
def maintenance_encode_library() -> tuple:
    manager = _manager()
    payload = request.get_json(silent=True) or {}
    scope = str(payload.get("scope", "all")).strip().lower()
    suffix = str(payload.get("suffix", ".x265.mkv")).strip() or ".x265.mkv"

    targets: list[Path] = []
    if scope in {"all", "movies"}:
        targets.append(manager.settings.movies_path)
    if scope in {"all", "tv"}:
        targets.append(manager.settings.tv_path)
    if not targets:
        return jsonify({"ok": False, "error": "scope must be one of all|movies|tv"}), 400

    task_ids: list[str] = []
    for root in targets:
        cmd = [
            sys.executable,
            "/app/scripts/encode_library.py",
            "--root",
            str(root),
            "--suffix",
            suffix,
        ]
        task = _create_task("encode-library", cmd)
        task_ids.append(task["id"])
        _task_executor.submit(_run_task, task["id"])

    return jsonify({"ok": True, "task_ids": task_ids}), 202


@api_bp.post("/maintenance/rename-library")
@require_auth
def maintenance_rename_library() -> tuple:
    manager = _manager()
    payload = request.get_json(silent=True) or {}
    scope = str(payload.get("scope", "all")).strip().lower()

    targets: list[Path] = []
    if scope in {"all", "movies"}:
        targets.append(manager.settings.movies_path)
    if scope in {"all", "tv"}:
        targets.append(manager.settings.tv_path)
    if not targets:
        return jsonify({"ok": False, "error": "scope must be one of all|movies|tv"}), 400

    task_ids: list[str] = []
    for root in targets:
        cmd = [
            sys.executable,
            "/app/scripts/rename_library.py",
            "--root",
            str(root),
        ]
        task = _create_task("rename-library", cmd)
        task_ids.append(task["id"])
        _task_executor.submit(_run_task, task["id"])

    return jsonify({"ok": True, "task_ids": task_ids}), 202


@api_bp.post("/maintenance/tasks/<task_id>/cancel")
@require_auth
def maintenance_cancel_task(task_id: str) -> tuple:
    with _task_lock:
        task = _tasks.get(task_id)
        if not task:
            return jsonify({"ok": False, "error": "task not found"}), 404

        state = str(task.get("state", ""))
        if state in {"complete", "failed", "canceled"}:
            return jsonify({"ok": False, "error": f"task already {state}"}), 409

        proc = _task_procs.get(task_id)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            task["state"] = "canceled"
            task["updated_at"] = datetime.utcnow().isoformat() + "Z"
            _append_task_log(task, "Cancellation requested")
            return jsonify({"ok": True}), 200

        # queued but not started yet
        task["state"] = "canceled"
        task["updated_at"] = datetime.utcnow().isoformat() + "Z"
        _append_task_log(task, "Canceled before start")
        return jsonify({"ok": True}), 200
