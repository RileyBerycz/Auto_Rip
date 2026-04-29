from __future__ import annotations

from pathlib import Path

from flask import Flask, send_from_directory, render_template_string, jsonify
from flask_cors import CORS

from .routes.api import api_bp
from .services.job_manager import JobManager
from .services.sse_manager import SSEManager
from .services.state_store import StateStore


def create_app() -> Flask:
    # Determine static folder path
    static_folder = Path(__file__).parent.parent / "static"
    
    app = Flask(__name__, static_folder=str(static_folder), static_url_path="/assets")
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

    # Serve static files and SPA
    @app.route("/")
    def index():
        index_path = static_folder / "index.html"
        if index_path.exists():
            return send_from_directory(str(static_folder), "index.html")
        else:
            return render_template_string("""
                <!DOCTYPE html>
                <html>
                <head><title>DvDRip</title></head>
                <body style="background: #f0f0f0; padding: 20px; font-family: sans-serif;">
                    <h1>Application Starting...</h1>
                    <p>Frontend assets are being loaded. Please refresh in a moment.</p>
                </body>
                </html>
            """), 503

    @app.route("/<path:path>")
    def serve_static(path):
        # Skip API routes (should not reach here due to blueprint)
        if path.startswith("api/"):
            return jsonify({"ok": False, "error": "not found"}), 404
        
        # Try to serve as a static file first
        file_path = static_folder / path
        if file_path.exists() and file_path.is_file():
            return send_from_directory(str(static_folder), path)
        
        # If not found, serve index.html for SPA routing
        index_path = static_folder / "index.html"
        if index_path.exists():
            return send_from_directory(str(static_folder), "index.html")
        else:
            return render_template_string("""
                <!DOCTYPE html>
                <html>
                <head><title>DvDRip</title></head>
                <body style="background: #f0f0f0; padding: 20px; font-family: sans-serif;">
                    <h1>Application Starting...</h1>
                    <p>Frontend assets are being loaded. Please refresh in a moment.</p>
                </body>
                </html>
            """), 503

    return app
