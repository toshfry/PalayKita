import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask

from app import db
from app.models import Setting, User


class SettingsAboutTests(unittest.TestCase):
    def setUp(self):
        import app.routes as routes

        routes.is_activated = lambda: True
        routes.get_server_status = lambda: {
            "is_running": False,
            "status_label": "Stopped",
            "wifi_url": "http://192.168.1.20:5000",
            "ip": "192.168.1.20",
            "port": 5000,
            "configured_port": 5000,
            "desktop_url": "http://127.0.0.1:5050",
            "status_detail": "Server is stopped.",
            "can_start": True,
            "can_stop": False,
        }
        routes.license_status = lambda: {
            "activated": True,
            "business_name": "PalayKita Rice Mill",
            "owner_name": "Owner",
            "license_type_display": "Lifetime",
            "issued_at_display": "2026-06-19",
            "expires_on_display": "Never",
            "days_remaining": "No expiration",
            "computer_id": "TEST-COMPUTER",
        }

        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.app = Flask(__name__, template_folder="../templates", static_folder="../static")
        self.app.config.update(
            SECRET_KEY="settings-about-test",
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

        user = User(username="admin", password_hash="x", role="admin", is_active=True)
        db.session.add_all([Setting(business_name="About Test Mill"), user])
        db.session.commit()

        self.app.register_blueprint(routes.main_bp)
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()
        try:
            self.tmp.cleanup()
        except PermissionError:
            pass

    def test_settings_about_panel_matches_palaykita_branding(self):
        html = self.client.get("/settings").get_data(as_text=True)
        about = re.search(r'<section class="settings-panel about-panel" id="about-palaykita">(?P<section>.*?)</section>', html, flags=re.S)

        self.assertIn('href="#about-palaykita"', html)
        self.assertIn("About", html)
        self.assertIsNotNone(about)
        about_html = about.group("section")
        self.assertIn("ABOUT", about_html)
        self.assertIn('<span class="about-info-icon">i</span>', about_html)
        self.assertIn('/static/icons/palaykita_logo.png', about_html)
        self.assertIn('class="about-wordmark"', about_html)
        self.assertIn("Rice Milling Profit Tracker", about_html)
        self.assertIn("Version: 1.1.18", about_html)
        self.assertIn("<span>Database</span><strong>SQLite</strong>", about_html)
        self.assertIn("<span>Backend</span><strong>Flask + SQLAlchemy</strong>", about_html)
        self.assertIn("<span>Reports</span><strong>openpyxl (.xlsx)</strong>", about_html)
        self.assertIn("<span>Web UI</span><strong>Flask Templates + Vanilla JS</strong>", about_html)
        self.assertIn("<span>Web Server</span><strong>Waitress (LAN)</strong>", about_html)
        self.assertIn('class="developer-detail-row"', about_html)
        self.assertIn("<span>Developer</span>", about_html)
        self.assertIn("John Lloyd Sereno", about_html)
        self.assertNotIn("@toshfry", about_html)
        self.assertNotIn("Current User", about_html)

    def test_about_tribute_easter_egg_is_hidden_until_developer_clicks(self):
        html = self.client.get("/settings").get_data(as_text=True)
        js = Path("static/js/app.js").read_text()

        self.assertIn("data-tribute-trigger", html)
        self.assertIn('id="fatherTributeModal"', html)
        self.assertIn("hidden", html)
        # The "In Loving Memory" wording now lives only inside the laurel emblem;
        # the separate heading below it was removed.
        self.assertNotIn("<h2 id=\"fatherTributeTitle\">", html)
        self.assertIn("Your love, sacrifices, and guidance will always be remembered.", html)
        self.assertIn("Thank you for everything.", html)
        self.assertNotIn("PalayKita was built with gratitude, inspired by the values you taught me.", html)
        self.assertNotIn("Forever grateful.", html)
        self.assertIn("data-tribute-close", html)

        # Award-style laurel emblem: local offline image, halo, inner text, year.
        self.assertIn("img/award_laurel_wreath.png", html)
        self.assertNotIn("cloudinary", html.lower())
        self.assertIn("tribute-halo", html)
        self.assertIn("tribute-laurel", html)
        self.assertIn("IN<br>LOVING<br>MEMORY", html)
        self.assertIn("1974", html)
        self.assertIn("2025", html)

        self.assertIn("[data-tribute-trigger]", js)
        self.assertIn("fatherTributeModal", js)
        self.assertIn("tributeClicks >= 5", js)

    def test_about_tribute_emblem_uses_award_laurel_image(self):
        html = self.client.get("/settings").get_data(as_text=True)
        css = Path("static/css/app.css").read_text()
        modal = re.search(r'<div class="tribute-modal" id="fatherTributeModal".*?</div>\s*</section>', html, flags=re.S)

        self.assertIsNotNone(modal)
        modal_html = modal.group(0)
        # Local offline laurel image only - no external / Cloudinary URL.
        self.assertIn("img/award_laurel_wreath.png", modal_html)
        self.assertNotIn("http://", modal_html)
        self.assertNotIn("https://", modal_html)
        self.assertNotIn("cloudinary", modal_html.lower())
        # Halo above, masked gold laurel, "IN LOVING MEMORY" inside, year below.
        self.assertIn('class="tribute-halo"', modal_html)
        self.assertIn('class="tribute-laurel"', modal_html)
        self.assertIn("mask-image", modal_html)
        self.assertIn("IN<br>LOVING<br>MEMORY", modal_html)
        self.assertIn('class="tribute-name"', modal_html)
        self.assertIn("ELMER D. SERENO", modal_html)
        self.assertIn('class="tribute-years"', modal_html)
        self.assertIn("1974", modal_html)
        self.assertIn("2025", modal_html)
        # Old emblems removed.
        self.assertNotIn("tribute-medallion", modal_html)
        self.assertNotIn("tribute-rice-icon", modal_html)
        self.assertNotIn("tributeBranch", modal_html)
        self.assertNotIn("tributeLeaf", modal_html)

        self.assertIn(".tribute-laurel", css)
        self.assertIn(".tribute-halo", css)
        self.assertIn("mask-size: contain", css)

    def test_settings_page_has_touch_friendly_responsive_navigation(self):
        html = self.client.get("/settings").get_data(as_text=True)
        css = Path("static/css/app.css").read_text()

        self.assertIn("settings-nav-shell", html)
        self.assertIn('aria-label="Settings sections"', html)
        self.assertIn('class="settings-nav-label"', html)
        self.assertIn('data-settings-nav', html)
        self.assertIn('class="settings-nav-link"', html)
        self.assertIn('class="settings-nav-index"', html)

        self.assertIn(".settings-nav-shell", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn(".settings-touch-hint", css)
        self.assertIn("@media (max-width: 1100px)", css)
        self.assertIn("@media (max-width: 700px)", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", css)

    def test_audit_log_filters_are_contained_in_settings_panel(self):
        html = self.client.get("/settings").get_data(as_text=True)
        css = Path("static/css/app.css").read_text()

        self.assertIn('class="directory-toolbar audit-filter-bar"', html)
        self.assertIn('class="audit-filter-actions"', html)
        self.assertIn(".audit-log-panel", css)
        self.assertIn(".audit-filter-bar > *", css)
        self.assertIn("grid-template-columns: minmax(220px, 1.4fr)", css)
        self.assertIn(".audit-filter-actions", css)
        self.assertNotIn(
            "grid-template-columns: minmax(220px, 1fr) 170px 170px 150px 150px auto auto;",
            css,
        )

    def test_global_date_inputs_use_compact_responsive_style(self):
        css = Path("static/css/app.css").read_text()
        web_html = Path("web/index.html").read_text(encoding="utf-8")
        desktop = Path("desktop.py").read_text(encoding="utf-8")

        self.assertIn('input[type="date"]', css)
        self.assertIn('input[type="time"]', css)
        self.assertIn("--date-field-calendar-icon", css)
        self.assertIn("--date-field-clock-icon", css)
        self.assertIn("-webkit-appearance: none", css)
        self.assertIn("appearance: none", css)
        self.assertIn("background-image: var(--date-field-calendar-icon)", css)
        self.assertIn("background-image: var(--date-field-clock-icon)", css)
        self.assertIn("background-position: right 18px center", css)
        self.assertIn('input[type="date"]::-webkit-date-and-time-value', css)
        self.assertIn('input[type="time"]::-webkit-date-and-time-value', css)
        self.assertIn("height: 50px", css)
        self.assertIn("min-height: 50px", css)
        self.assertIn("line-height: 50px", css)
        self.assertIn("text-align: left", css)
        self.assertIn("font-weight: 600", css)
        self.assertIn("font-variant-numeric: tabular-nums", css)
        self.assertIn(".filter-card > *", css)
        self.assertIn(".form-grid > *", css)
        self.assertIn(".filter-card > .btn", css)
        self.assertIn("@media (max-width: 700px)", css)
        self.assertIn("height: 48px", css)
        self.assertIn("padding: 0 46px 0 16px", css)
        self.assertIn("font-size: 15px", css)
        self.assertIn('input[type="date"], input[type="time"]', web_html)
        self.assertIn("--date-field-calendar-icon", web_html)
        self.assertIn("background-image:var(--date-field-calendar-icon)", web_html)
        self.assertIn("height:48px", web_html)
        self.assertIn("def date_entry", desktop)
        self.assertIn("font_size=11", desktop)
        self.assertGreaterEqual(desktop.count("date_entry("), 4)


if __name__ == "__main__":
    unittest.main()
