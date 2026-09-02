"""Public, unauthenticated endpoints.

Every route here is reachable without credentials, so these are the endpoints
most exposed to request floods.
"""

from flask import Blueprint, current_app, jsonify, request

from extensions import db
from models import Bookmark

public = Blueprint("public", __name__, url_prefix="/api")


@public.get("/status")
def status():
    return jsonify(status="ok")


@public.get("/search")
def search():
    """Full-text-ish search over public bookmarks.

    This runs an unbounded LIKE query on every call, so it is the most
    expensive public endpoint in the app.
    """
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify(error="q is required"), 400

    page_size = min(
        int(request.args.get("page_size", current_app.config["DEFAULT_PAGE_SIZE"])),
        current_app.config["MAX_PAGE_SIZE"],
    )

    rows = (
        db.session.query(Bookmark)
        .filter(Bookmark.title.ilike(f"%{query}%"))
        .order_by(Bookmark.created_at.desc())
        .limit(page_size)
        .all()
    )
    return jsonify(results=[r.to_dict() for r in rows])


@public.post("/feedback")
def feedback():
    """Accept anonymous feedback. Writes one row per call."""
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify(error="message is required"), 400
    current_app.logger.info("feedback received: %s", message[:200])
    return jsonify(ok=True), 201
