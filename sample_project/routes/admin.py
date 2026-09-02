"""Admin endpoints, guarded by a static API key header."""

from functools import wraps

from flask import Blueprint, jsonify, request

from extensions import db
from models import Bookmark, User

admin = Blueprint("admin", __name__, url_prefix="/api/admin")


def require_api_key(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key")
        if not key:
            return jsonify(error="missing_api_key"), 401
        user = db.session.query(User).filter_by(api_key=key).one_or_none()
        if user is None:
            return jsonify(error="invalid_api_key"), 403
        request.current_user = user
        return view(*args, **kwargs)

    return wrapper


@admin.get("/stats")
@require_api_key
def stats():
    return jsonify(
        users=db.session.query(User).count(),
        bookmarks=db.session.query(Bookmark).count(),
    )


@admin.delete("/bookmarks/<int:bookmark_id>")
@require_api_key
def delete_bookmark(bookmark_id):
    row = db.session.get(Bookmark, bookmark_id)
    if row is None:
        return jsonify(error="not_found"), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify(ok=True)
