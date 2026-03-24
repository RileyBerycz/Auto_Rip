from __future__ import annotations

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

from .routes.api import api_bp
from .services.job_manager import JobManager
from .services.state_store import StateStore

socketio = SocketIO(cors_allowed_origins="*")


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
        "OLLAMA_URL",
        "OLLAMA_MODEL",
        "RUNTIME_TOLERANCE_MINUTES",
        "MAX_IDENTIFY_WORKERS",
        "DISC_CACHE_DB",
    ]
    saved = store.get_settings(settings_keys)

    manager = JobManager(socketio, settings_overrides=saved)
    app.extensions["job_manager"] = manager
    app.extensions["state_store"] = store

    app.register_blueprint(api_bp, url_prefix="/api")
    socketio.init_app(app)

    return app
