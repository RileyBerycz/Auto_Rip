from __future__ import annotations

import os

from flask import Flask, send_from_directory
from flask_cors import CORS

from .routes.api import api_bp
from .services.job_manager import JobManager
from .services.sse_manager import SSEManager
from .services.state_store import StateStore


def create_app() -> Flask:
    app = Flask(__name__, static_folder="../static", static_url_path="")
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

    # Serve React frontend; fallback to index.html for SPA routing
    @app.route("/")
    def serve_index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/<path:path>")
    def serve_static(path):
        # Try serving static file first
        file_path = os.path.join(app.static_folder, path)
        if os.path.isfile(file_path):
            return send_from_directory(app.static_folder, path)
        # Fallback to index.html for SPA routing
        return send_from_directory(app.static_folder, "index.html")

    return app
