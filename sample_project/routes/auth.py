"""Token issuing endpoints.

These are public too, which makes /api/auth/token a credential stuffing target.
"""

import hashlib
import secrets

from flask import Blueprint, jsonify, request

from extensions import db
from models import User

auth = Blueprint("auth", __name__, url_prefix="/api/auth")


def _hash(password):
    return hashlib.sha256(password.encode()).hexdigest()


@auth.post("/token")
def issue_token():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    user = db.session.query(User).filter_by(email=email).one_or_none()
    if user is None or user.password_hash != _hash(password):
        # No delay, no attempt counter, no lockout.
        return jsonify(error="invalid_credentials"), 401

    user.api_key = secrets.token_urlsafe(32)
    db.session.commit()
    return jsonify(api_key=user.api_key)
