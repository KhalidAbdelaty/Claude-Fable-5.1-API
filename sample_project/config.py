"""Configuration objects for the Bookmarks API."""

import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///bookmarks.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Pagination for the search endpoint.
    DEFAULT_PAGE_SIZE = 25
    MAX_PAGE_SIZE = 100

    # Token lifetime for the auth blueprint, in seconds.
    TOKEN_TTL = 3600

    # There is no throttling configuration yet. Anything that limits request
    # volume per client would need to be added here first.


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
