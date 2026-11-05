from flask import Flask

from . import db
from .config import Config
from .models import ModelRegistry
from .routes import api, pages


def create_app(config=Config):
    app = Flask(__name__, static_url_path="")
    app.config.from_object(config)

    db.init_app(app)

    registry = ModelRegistry(app.config["MODEL_DIR"], app.config["MODEL_MODES"])
    registry.load()
    app.extensions["models"] = registry

    app.register_blueprint(pages)
    app.register_blueprint(api)
    return app
