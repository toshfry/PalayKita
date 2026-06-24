import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask

from app import db
from app.models import Setting


class LoginBrandingTests(unittest.TestCase):
    def setUp(self):
        import app.routes as routes

        routes.is_activated = lambda: True
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)

        self.app = Flask(__name__, template_folder="../templates", static_folder="../static")
        self.app.config.update(
            SECRET_KEY="login-brand-test",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
            EXPORT_DIR=root / "exports",
            DAILY_REPORT_DIR=root / "exports" / "daily",
            WEEKLY_REPORT_DIR=root / "exports" / "weekly",
            MONTHLY_REPORT_DIR=root / "exports" / "monthly",
            CUSTOM_REPORT_DIR=root / "exports" / "custom",
            COMMERCIAL_REPORT_DIR=root / "exports" / "commercial",
            BACKUP_DIR=root / "backups",
        )
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        db.session.add(Setting())
        db.session.commit()

        self.app.register_blueprint(routes.main_bp)
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()
        try:
            self.tmp.cleanup()
        except PermissionError:
            pass

    def test_login_uses_logo_image_and_split_color_wordmark(self):
        html = self.client.get("/login").get_data(as_text=True)

        self.assertIn('/static/icons/palaykita_logo.png', html)
        self.assertIn('alt="PalayKita logo"', html)
        self.assertIn('class="word-palay">Palay</span>', html)
        self.assertIn('class="word-kita">Kita</span>', html)
        self.assertIn("color: #D69C0B;", html)
        self.assertIn("color: #056C27;", html)
        self.assertIn("PalayKita v1.1.18", html)


if __name__ == "__main__":
    unittest.main()
