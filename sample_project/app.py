"""Application factory for the Bookmarks API."""

from flask import Flask, jsonify

from config import Config
from extensions import db
from routes.admin import admin
from routes.auth import auth
from routes.public import public


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    db.init_app(app)

    app.register_blueprint(public)
    app.register_blueprint(auth)
    app.register_blueprint(admin)

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="not_found"), 404

    @app.errorhandler(500)
    def server_error(_):
        return jsonify(error="server_error"), 500

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
