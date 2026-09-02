"""Database models for the Bookmarks API."""

from datetime import datetime, timezone

from extensions import db


def _now():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    api_key = db.Column(db.String(64), unique=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now)

    bookmarks = db.relationship("Bookmark", back_populates="user")


class Bookmark(db.Model):
    __tablename__ = "bookmarks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    url = db.Column(db.Text, nullable=False)
    title = db.Column(db.String(500))
    tags = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime(timezone=True), default=_now)

    user = db.relationship("User", back_populates="bookmarks")

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "tags": [t for t in (self.tags or "").split(",") if t],
        }
