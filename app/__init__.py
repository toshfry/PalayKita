from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from config import Config


db = SQLAlchemy()
APP_VERSION = "1.1.18"


def create_app():
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static"
    )

    app.config.from_object(Config)

    from app.utils import ensure_project_folders
    ensure_project_folders(app)

    db.init_app(app)

    with app.app_context():
        from app import models  # noqa: F401
        from app.seed import seed_defaults

        db.create_all()
        seed_defaults()

    from app.routes import main_bp
    app.register_blueprint(main_bp)

    return app
