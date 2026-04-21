from __future__ import annotations

from flask import Flask
from flask_cors import CORS

from .routes.api import api_bp
from .services.job_manager import JobManager
from .services.sse_manager import SSEManager
from .services.state_store import StateStore


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    app.config["BACKEND_HOST"] = "0.0.0.0"
    app.config["BACKEND_PORT"] = 7272

    store = StateStore()
    settings_keys = [
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
    saved = store.get_settings(settings_keys)

    sse_manager = SSEManager()
    manager = JobManager(sse_manager, settings_overrides=saved)
    app.extensions["job_manager"] = manager
    app.extensions["state_store"] = store
    app.extensions["sse_manager"] = sse_manager

    app.register_blueprint(api_bp, url_prefix="/api")

    return app
