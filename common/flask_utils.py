"""Small helpers shared by every service (NOT shared business logic or data)."""
import sqlite3
import sys
from pathlib import Path

from flask import Flask, jsonify

from common import service_client


def make_app(service_name):
    app = Flask(service_name)
    app.json.sort_keys = False

    @app.get("/health")
    def health():
        return jsonify({"service": service_name, "status": "UP",
                        "circuit_breakers": service_client.all_breaker_states()})

    @app.errorhandler(404)
    def _404(_):
        return jsonify({"error": "resource not found"}), 404

    @app.errorhandler(405)
    def _405(_):
        return jsonify({"error": "method not allowed"}), 405

    @app.errorhandler(500)
    def _500(e):
        return jsonify({"error": "internal server error"}), 500

    return app


def open_db(db_file):
    """Each service passes ITS OWN db file. autocommit mode; use BEGIN explicitly."""
    Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


def quiet_werkzeug():
    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def service_dir(file):
    return Path(file).resolve().parent


def add_project_root(file):
    root = str(Path(file).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
