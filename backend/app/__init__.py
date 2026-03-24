from __future__ import annotations

from flask import Flask
from flask_socketio import SocketIO

from .routes.api import api_bp
from .services.job_manager import JobManager

socketio = SocketIO(cors_allowed_origins="*")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["BACKEND_HOST"] = "0.0.0.0"
    app.config["BACKEND_PORT"] = 7272

    manager = JobManager(socketio)
    app.extensions["job_manager"] = manager

    app.register_blueprint(api_bp, url_prefix="/api")
    socketio.init_app(app)

    return app
