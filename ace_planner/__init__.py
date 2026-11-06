"""ACE Cohort Event Planner: Flask application factory."""

from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Any

from flask import Flask, current_app, render_template

from .models import db
from .security import check_csrf, csrf_token, load_admin

__all__ = ["create_app", "current_time"]


def current_time() -> datetime:
    """App clock. ``ACE_NOW`` pins it (demos and tests); otherwise local time."""
    pinned = current_app.config.get("NOW")
    if pinned:
        return datetime.fromisoformat(pinned) if isinstance(pinned, str) else pinned
    return datetime.now()


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", f"sqlite:///{os.path.join(app.instance_path, 'ace_planner.db')}"
        ),
        NOW=os.environ.get("ACE_NOW"),
        MAX_CONTENT_LENGTH=1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)
    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)

    app.before_request(load_admin)
    app.before_request(check_csrf)
    app.jinja_env.globals["csrf_token"] = csrf_token

    from .views import bp

    app.register_blueprint(bp)

    @app.errorhandler(400)
    @app.errorhandler(404)
    def http_error(err):  # type: ignore[no-untyped-def]
        return render_template("error.html", error=err), err.code

    from . import seed

    seed.register_cli(app)
    with app.app_context():
        db.create_all()
    return app
