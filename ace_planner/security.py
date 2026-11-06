"""Admin authentication, CSRF protection, and safe redirects."""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from functools import wraps
from typing import Any
from urllib.parse import urlsplit

from flask import abort, g, redirect, request, session, url_for

from .models import Admin, db


def is_safe_next(target: str | None) -> bool:
    """Only allow same-site relative paths, which blocks open redirects."""
    if not target:
        return False
    parts = urlsplit(target)
    return (not parts.scheme and not parts.netloc and target.startswith("/")
            and not target.startswith("//") and "\\" not in target)


def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def check_csrf() -> None:
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(sent, session.get("_csrf", "")):
            abort(400, description="Form expired or invalid. Please reload and try again.")


def load_admin() -> None:
    admin_id = session.get("admin_id")
    g.admin = db.session.get(Admin, admin_id) if admin_id else None


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if g.get("admin") is None:
            return redirect(url_for("main.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def authenticate(username: str, password: str) -> Admin | None:
    admin = Admin.query.filter_by(username=username.strip()).first()
    if admin and admin.check_password(password):
        return admin
    return None
