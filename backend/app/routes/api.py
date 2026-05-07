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

from flask import Blueprint, current_app, jsonify, request, Response
import requests

from dvdflix_core.config import discover_optical_drives
from dvdflix_core.library import discover_media_items
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


def _resolve_library_path(root: Path, path_value: str) -> Path:
    if not path_value:
        raise ValueError("path is required")
    candidate = Path(path_value)
    root_resolved = root.resolve(strict=False)
    target = candidate.resolve(strict=False) if candidate.is_absolute() else (root_resolved / candidate).resolve(strict=False)
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError("path must be inside the library root")
    return target


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
    # For SSE, check query param
    return request.args.get("token", "")


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
        "HANDBRAKE_PRESET_DVD",
        "HANDBRAKE_PRESET_BLURAY",
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
        "HANDBRAKE_PRESET_DVD",
        "HANDBRAKE_PRESET_BLURAY",
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


@api_bp.get("/healthcheck")
def healthcheck() -> tuple:
    """Lightweight unauthenticated health endpoint for Docker healthchecks."""
    manager = _manager()
    store = _store()
    return (
        jsonify(
            {
                "ok": True,
                "configured": store.is_setup_complete(),
                "drives": manager.settings.drives,
                "movies_path": str(manager.settings.movies_path),
                "tv_path": str(manager.settings.tv_path),
            }
        ),
        200,
    )


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


@api_bp.get("/setup/ollama-models")
def setup_ollama_models() -> tuple:
    """Attempt to query the configured Ollama URL (or provided url query param)
    and return a simple list of model names. This endpoint is intentionally
    unauthenticated so it can be used during initial setup.
    Query param: url (optional) — overrides stored OLLAMA_URL.
    """
    manager = _manager()
    url = (request.args.get("url") or manager.settings.ollama_url or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "Ollama URL not configured"}), 400

    candidates = ["/models", "/api/models", "/v1/models"]
    models = None
    last_error = None
    for ep in candidates:
        try:
            full = url.rstrip("/") + ep
            resp = requests.get(full, timeout=5)
            if not resp.ok:
                last_error = f"HTTP {resp.status_code} from {full}"
                continue
            payload = resp.json()
            # payload may be list or dict; normalize to list of names
            models = []
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, str):
                        models.append(item)
                    elif isinstance(item, dict):
                        name = item.get("name") or item.get("id") or item.get("model")
                        if name:
                            models.append(name)
            elif isinstance(payload, dict):
                # try common shapes: { "models": [...] } or OpenAI-like { "object":"list","data":[...] }
                if "models" in payload and isinstance(payload["models"], list):
                    for item in payload["models"]:
                        if isinstance(item, str):
                            models.append(item)
                        elif isinstance(item, dict):
                            name = item.get("name") or item.get("id") or item.get("model")
                            if name:
                                models.append(name)
                elif "data" in payload and isinstance(payload["data"], list):
                    for item in payload["data"]:
                        if isinstance(item, str):
                            models.append(item)
                        elif isinstance(item, dict):
                            # Ollama and some APIs embed model metadata under name/id/model
                            name = item.get("name") or item.get("id") or item.get("model") or item.get("modelName")
                            if name:
                                models.append(name)
                else:
                    # as a fallback, use keys
                    models = list(payload.keys())
            if models is not None:
                break
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue

    if models is None:
        return jsonify({"ok": False, "error": f"could not query Ollama models: {last_error}"}), 502

    # dedupe and return
    seen = []
    for m in models:
        if m not in seen:
            seen.append(m)

    return jsonify({"ok": True, "models": seen}), 200


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
        "lsdvd": Path("/usr/bin/lsdvd").exists() or bool(shutil.which("lsdvd")),
        "makemkvcon": Path(settings.makemkvcon_path).exists() or Path("/usr/bin/makemkvcon").exists(),
        "eject": Path("/usr/bin/eject").exists() or bool(shutil.which("eject")),
        "handbrake": bool(shutil.which("HandBrakeCLI")),
    }

    # Use both configured drives and runtime-detected drives to assess availability.
    detected = discover_optical_drives()
    all_drives = sorted(set(list(settings.drives or []) + list(detected or [])))
    drive_status = {drive: Path(drive).exists() for drive in all_drives}

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
                "tools": {
                    "lsdvd": tools["lsdvd"],
                    "makemkvcon": tools["makemkvcon"],
                    "eject": tools["eject"],
                    "handbrake": tools["handbrake"],
                    "lsdvd_path": "/usr/bin/lsdvd" if tools["lsdvd"] else None,
                    "makemkvcon_path": str(settings.makemkvcon_path) if tools["makemkvcon"] else None,
                },
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


@api_bp.get("/dashboard")
@require_auth
def dashboard() -> tuple:
    manager = _manager()
    settings = manager.settings

    drive_statuses = manager.list_drive_statuses()
    drives_summary = {
        "total": len(drive_statuses),
        "with_disc": sum(1 for d in drive_statuses if d.get("has_disc")),
        "readable": sum(1 for d in drive_statuses if d.get("readable")),
    }

    library_payload = {
        "movies": discover_media_items(settings.movies_path, "movie", settings.tmdb_api_key),
        "tvshows": discover_media_items(settings.tv_path, "tv", settings.tmdb_api_key),
        "movies_path": str(settings.movies_path),
        "movies_path_exists": settings.movies_path.exists(),
        "tv_path": str(settings.tv_path),
        "tv_path_exists": settings.tv_path.exists(),
    }

    with _task_lock:
        ordered = sorted(_tasks.values(), key=lambda x: x.get("updated_at", ""), reverse=True)
    library_jobs = []
    for job in manager.list_jobs():
        if job.get("drive"):
            continue
        if not job.get("title", "").lower().startswith("library encode"):
            continue
        library_jobs.append(
            {
                "id": job["id"],
                "kind": "library-encode",
                "state": job["state"],
                "title": job.get("title", ""),
                "output_path": job.get("output_path", ""),
                "logs": job.get("logs", []),
                "updated_at": job.get("updated_at", ""),
            }
        )
    maintenance_combined = sorted(ordered + library_jobs, key=lambda x: x.get("updated_at", ""), reverse=True)

    return jsonify(
        {
            "ok": True,
            "health": {
                "ok": True,
                "drives": manager.settings.drives,
                "movies_path": str(settings.movies_path),
                "tv_path": str(settings.tv_path),
            },
            "jobs": manager.list_jobs(),
            "library": library_payload,
            "capabilities": {
                "ok": True,
                "capabilities": {
                        "lsdvd": bool(shutil.which("lsdvd")),
                        "makemkvcon": _tool_exists(settings.makemkvcon_path),
                        "eject": bool(shutil.which("eject")),
                        "handbrake": bool(shutil.which("HandBrakeCLI")),
                },
                "drive_status": {drive: Path(drive).exists() for drive in sorted(set(list(settings.drives or []) + list(discover_optical_drives() or [])))},
                "paths": {
                    "movies": {"path": str(settings.movies_path), "exists": settings.movies_path.exists()},
                    "tv": {"path": str(settings.tv_path), "exists": settings.tv_path.exists()},
                    "temp": {"path": str(settings.temp_rip_path), "exists": settings.temp_rip_path.exists()},
                },
            },
            "settings": {"ok": True, "settings": settings.to_runtime_dict()},
            "profile": {"ok": True, "profile": _store().get_settings(_profile_setting_keys())},
            "history": {"ok": True, "history": manager.list_history(limit=500)},
            "accounts": {"ok": True, "users": _store().list_users(), "current_user": _current_user()},
            "drives": {"ok": True, "drives": drive_statuses, "summary": drives_summary},
            "temp_files": {
                "ok": True,
                "root": str(settings.temp_rip_path),
                "exists": settings.temp_rip_path.exists(),
                "entries": _list_temp_entries(settings.temp_rip_path),
                "summary": {},
            },
            "maintenance": {"ok": True, "tasks": maintenance_combined[:50]},
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

    movies_path = manager.settings.movies_path
    tv_path = manager.settings.tv_path
    return (
        jsonify(
            {
                "movies": discover_media_items(movies_path, "movie", manager.settings.tmdb_api_key),
                "tvshows": discover_media_items(tv_path, "tv", manager.settings.tmdb_api_key),
                "movies_path": str(movies_path),
                "movies_path_exists": movies_path.exists(),
                "tv_path": str(tv_path),
                "tv_path_exists": tv_path.exists(),
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
    media_type = str(payload.get("media_type", "movie")).strip().lower()
    
    if not title:
        return jsonify({"ok": False, "error": "title is required"}), 400
    if media_type not in {"movie", "tv"}:
        return jsonify({"ok": False, "error": "media_type must be movie or tv"}), 400

    parsed_year: int | None = None
    if year:
        if not year.isdigit():
            return jsonify({"ok": False, "error": "year must be numeric"}), 400
        parsed_year = int(year)
    
    job = _manager().get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404
    
    result = _manager().finalize_manual_identification(
        job_id,
        title=title,
        media_type=media_type,
        year=parsed_year,
    )
    code = 200 if result.get("ok") else 409
    return jsonify(result), code


@api_bp.post("/search/tmdb")
@require_auth
def search_tmdb() -> tuple:
    """
    Search TMDB for titles to help with manual overrides.
    Payload: { "query": "The Matrix", "media_type": "movie|tv" }
    """
    from dvdflix_core.clients import TmdbClient
    
    payload = request.get_json(silent=True) or {}
    query = str(payload.get("query", "")).strip()
    media_type = str(payload.get("media_type", "movie")).strip().lower()
    
    if not query:
        return jsonify({"ok": False, "error": "query is required"}), 400
    if media_type not in {"movie", "tv"}:
        return jsonify({"ok": False, "error": "media_type must be movie or tv"}), 400
    
    manager = _manager()
    tmdb = TmdbClient(api_key=manager.settings.tmdb_api_key)
    
    try:
        if media_type == "tv":
            results = tmdb.search_tv(query)
        else:
            results = tmdb.search_movie(query)
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

    manager = _manager()
    library_tasks = []
    for job in manager.list_jobs():
        if job.get("drive"):
            continue
        if not job.get("title", "").lower().startswith("library encode"):
            continue
        library_tasks.append(
            {
                "id": job["id"],
                "kind": "library-encode",
                "state": job["state"],
                "title": job.get("title", ""),
                "output_path": job.get("output_path", ""),
                "logs": job.get("logs", []),
                "updated_at": job.get("updated_at", ""),
            }
        )

    combined = sorted(ordered + library_tasks, key=lambda x: x.get("updated_at", ""), reverse=True)
    return jsonify({"ok": True, "tasks": combined[:50]}), 200


@api_bp.post("/maintenance/encode-library")
@require_auth
def maintenance_encode_library() -> tuple:
    manager = _manager()
    payload = request.get_json(silent=True) or {}
    scope = str(payload.get("scope", "all")).strip().lower()

    result = manager.queue_library_encode(scope)
    status = 202 if result.get("ok") else 400
    return jsonify(result), status


@api_bp.post("/maintenance/encode-item")
@require_auth
def maintenance_encode_item() -> tuple:
    manager = _manager()
    payload = request.get_json(silent=True) or {}
    scope = str(payload.get("scope", "movies")).strip().lower()
    rel_path = str(payload.get("path", "")).strip()

    if scope not in {"movies", "tv"}:
        return jsonify({"ok": False, "error": "scope must be movies or tv"}), 400

    root = manager.settings.movies_path if scope == "movies" else manager.settings.tv_path
    try:
        target = _resolve_library_path(root, rel_path)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    result = manager.queue_library_encode_item(target, scope)
    status = 202 if result.get("ok") else 400
    return jsonify(result), status


@api_bp.post("/maintenance/rename-library")
@require_auth
def maintenance_rename_library() -> tuple:
    manager = _manager()
    payload = request.get_json(silent=True) or {}
    scope = str(payload.get("scope", "all")).strip().lower()

    script_path = Path("/app/scripts/rename_library.py")
    if not script_path.exists():
        return jsonify({"ok": False, "error": f"missing script: {script_path}"}), 500

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


@api_bp.post("/maintenance/rename-item")
@require_auth
def maintenance_rename_item() -> tuple:
    manager = _manager()
    payload = request.get_json(silent=True) or {}
    scope = str(payload.get("scope", "movies")).strip().lower()
    rel_path = str(payload.get("path", "")).strip()
    use_llm = bool(payload.get("use_llm", False))

    if scope not in {"movies", "tv"}:
        return jsonify({"ok": False, "error": "scope must be movies or tv"}), 400

    root = manager.settings.movies_path if scope == "movies" else manager.settings.tv_path
    try:
        target = _resolve_library_path(root, rel_path)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if not target.exists():
        return jsonify({"ok": False, "error": f"path not found: {target}"}), 404

    script_path = Path("/app/scripts/rename_library.py")
    if not script_path.exists():
        return jsonify({"ok": False, "error": f"missing script: {script_path}"}), 500

    cmd = [
        sys.executable,
        "/app/scripts/rename_library.py",
        "--path",
        str(target),
    ]
    if use_llm:
        cmd.append("--use-llm")
    task = _create_task("rename-item", cmd)
    _task_executor.submit(_run_task, task["id"])
    return jsonify({"ok": True, "task_id": task["id"]}), 202


@api_bp.post("/maintenance/generate-nfos")
@require_auth
def maintenance_generate_nfos() -> tuple:
    manager = _manager()
    payload = request.get_json(silent=True) or {}
    scope = str(payload.get("scope", "all")).strip().lower()

    script_path = Path("/app/scripts/generate_nfo.py")
    if not script_path.exists():
        return jsonify({"ok": False, "error": f"missing script: {script_path}"}), 500

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
            "/app/scripts/generate_nfo.py",
            "--root",
            str(root),
        ]
        if manager.settings.tmdb_api_key:
            cmd.extend(["--tmdb-key", manager.settings.tmdb_api_key])
        task = _create_task("generate-nfos", cmd)
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


@api_bp.get("/events")
@require_auth
def events() -> Response:
    import queue

    sse_manager = current_app.extensions["sse_manager"]
    client_id = str(uuid.uuid4())

    def generate():
        q = sse_manager.add_client(client_id)
        try:
            while True:
                try:
                    message = q.get(timeout=30)
                    yield message
                except queue.Empty:
                    yield "data: keepalive\n\n"
        finally:
            sse_manager.remove_client(client_id)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api_bp.get("/logs")
@require_auth
def list_logs() -> tuple:
    """List available log files in the backend's log directory."""
    log_dir = Path("/app/logs")
    if not log_dir.exists():
        return jsonify({"ok": True, "logs": [], "live_log": None}), 200

    entries = []
    for p in sorted(log_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file() and p.suffix in {".log", ".txt"}:
            entries.append({
                "name": p.name,
                "size": p.stat().st_size,
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
            })
    return jsonify({"ok": True, "logs": entries, "live_log": "backend.log"}), 200


@api_bp.get("/logs/<name>")
@require_auth
def get_log(name: str) -> tuple:
    """Return the last N lines of a log file."""
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "._-")
    if safe != name:
        return jsonify({"ok": False, "error": "Invalid log name"}), 400

    log_dir = Path("/app/logs")
    target = (log_dir / safe).resolve()
    if not str(target).startswith(str(log_dir.resolve())):
        return jsonify({"ok": False, "error": "Access denied"}), 403

    if not target.exists():
        return jsonify({"ok": False, "error": "Log not found"}), 404

    raw_limit = request.args.get("limit", "500")
    try:
        limit = max(10, min(5000, int(raw_limit)))
    except ValueError:
        limit = 500

    try:
        lines = target.read_text(errors="replace").splitlines()
        tail = lines[-limit:]
        return jsonify({"ok": True, "name": name, "lines": tail, "total_lines": len(lines)}), 200
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api_bp.post("/library/rename-item")
@require_auth
def rename_item() -> tuple:
    """Manually rename a single library item."""
    manager = _manager()
    payload = request.get_json(silent=True) or {}
    scope = str(payload.get("scope", "movies")).strip().lower()
    rel_path = str(payload.get("path", "")).strip()

    if scope not in {"movies", "tv"}:
        return jsonify({"ok": False, "error": "scope must be movies or tv"}), 400

    root = manager.settings.movies_path if scope == "movies" else manager.settings.tv_path
    try:
        target = _resolve_library_path(root, rel_path)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if not target.exists():
        return jsonify({"ok": False, "error": f"Path not found: {target}"}), 404

    # Queue a rename task for this single item
    script_path = Path("/app/scripts/rename_library.py")
    if not script_path.exists():
        return jsonify({"ok": False, "error": f"Missing script: {script_path}"}), 500

    cmd = [sys.executable, str(script_path), "--path", str(target)]
    task = _create_task("rename-item", cmd)
    _task_executor.submit(_run_task, task["id"])
    return jsonify({"ok": True, "task_id": task["id"]}), 202


@api_bp.get("/thumbnail")
@require_auth
def thumbnail() -> Response:
    """Serve a thumbnail image from the library by relative path."""
    rel = request.args.get("path", "").strip()
    scope = request.args.get("scope", "movies").strip().lower()
    if scope not in {"movies", "tv"}:
        return jsonify({"ok": False, "error": "scope must be movies or tv"}), 400

    manager = _manager()
    root = manager.settings.movies_path if scope == "movies" else manager.settings.tv_path
    try:
        target = _resolve_library_path(root, rel)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    # Look for common thumbnail files
    candidates = [
        target.with_suffix(".jpg"),
        target.with_suffix(".png"),
        target / "poster.jpg",
        target / "poster.png",
        Path(str(target) + "-poster.jpg"),
    ]
    found = next((p for p in candidates if p.exists()), None)
    if not found:
        return jsonify({"ok": False, "error": "thumbnail not found"}), 404

    mime = "image/jpeg" if found.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return Response(found.read_bytes(), mimetype=mime)
