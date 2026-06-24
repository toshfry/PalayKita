import re
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask

from app import db
from app.models import (
    CommercialCustomer,
    CommercialTransaction,
    MillingTransaction,
    Setting,
    User,
)


class DashboardTotalsTests(unittest.TestCase):
    def setUp(self):
        import app.routes as routes

        routes.is_activated = lambda: True
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)

        self.app = Flask(__name__, template_folder="../templates", static_folder="../static")
        self.app.config.update(
            SECRET_KEY="dashboard-test",
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
        settings = Setting(business_name="Dashboard Mill")
        customer = CommercialCustomer(name="Commercial Buyer", status="Active")
        db.session.add_all([user, settings, customer])
        db.session.flush()

        local = MillingTransaction(
            transaction_number="TRX-DASH-0001",
            customer_name="Local Customer",
            kilos_milled=Decimal("100.00"),
            milling_rate_per_kg=Decimal("5.00"),
            gross_fee=Decimal("500.00"),
            has_chaff_deduction=False,
            chaff_kilos=Decimal("0.00"),
            chaff_rate_per_kg=Decimal("0.00"),
            chaff_deduction=Decimal("0.00"),
            net_amount=Decimal("500.00"),
            amount_paid=Decimal("300.00"),
            balance=Decimal("200.00"),
            payment_status="Partial",
            transaction_date=date.today(),
        )
        commercial = CommercialTransaction(
            transaction_number="COM-DASH-0001",
            customer_id=customer.id,
            number_of_sacks=Decimal("2.00"),
            price_per_sack=Decimal("1000.00"),
            total_amount=Decimal("2000.00"),
            amount_paid=Decimal("500.00"),
            balance=Decimal("1500.00"),
            payment_status="Partial",
            transaction_date=date.today(),
        )
        commercial_same_customer = CommercialTransaction(
            transaction_number="COM-DASH-0002",
            customer_id=customer.id,
            number_of_sacks=Decimal("1.00"),
            price_per_sack=Decimal("1000.00"),
            total_amount=Decimal("1000.00"),
            amount_paid=Decimal("0.00"),
            balance=Decimal("1000.00"),
            payment_status="Unpaid",
            transaction_date=date.today(),
        )
        paid_local = MillingTransaction(
            transaction_number="TRX-DASH-PAID",
            customer_name="Paid Local",
            kilos_milled=Decimal("10.00"),
            milling_rate_per_kg=Decimal("5.00"),
            gross_fee=Decimal("50.00"),
            has_chaff_deduction=False,
            chaff_kilos=Decimal("0.00"),
            chaff_rate_per_kg=Decimal("0.00"),
            chaff_deduction=Decimal("0.00"),
            net_amount=Decimal("50.00"),
            amount_paid=Decimal("50.00"),
            balance=Decimal("0.00"),
            payment_status="Paid",
            transaction_date=date.today(),
        )
        db.session.add_all([local, commercial, commercial_same_customer, paid_local])
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

    def test_dashboard_hero_shows_cash_collected_not_total_charges(self):
        response = self.client.get("/dashboard")
        html = response.get_data(as_text=True)

        hero = re.search(
            r'<div class="hero-amount">\s*(?P<amount>.*?)\s*<small>(?P<label>.*?)</small>',
            html,
            flags=re.S,
        )

        self.assertIsNotNone(hero)
        self.assertIn("850.00", hero.group("amount"))
        self.assertEqual(hero.group("label").strip(), "Cash Collected Today")
        self.assertIn("Income Today", html)
        self.assertIn("3,550.00", html)

    def test_dashboard_separates_local_commercial_and_total_metrics(self):
        response = self.client.get("/dashboard")
        html = response.get_data(as_text=True)

        expectations = {
            "transactions-local": "2",
            "transactions-commercial": "2",
            "transactions-total": "4",
            "income-local": "550.00",
            "income-commercial": "3,000.00",
            "income-total": "3,550.00",
            "paid-local": "350.00",
            "paid-commercial": "500.00",
            "paid-total": "850.00",
            "unpaid-local": "200.00",
            "unpaid-commercial": "2,500.00",
            "unpaid-total": "2,700.00",
            "unpaid-accounts-local": "1",
            "unpaid-accounts-commercial": "2",
            "unpaid-accounts-total": "3",
            "local-kilos": "110.00 kg",
            "commercial-sacks": "3.00 sacks",
        }

        for test_id, expected in expectations.items():
            pattern = rf'data-testid="{test_id}"[^>]*>\s*[^<]*{re.escape(expected)}'
            self.assertRegex(html, pattern)

    def test_dashboard_recent_transactions_filter_by_type_and_status(self):
        commercial_html = self.client.get("/dashboard?recent_filter=Commercial").get_data(as_text=True)
        self.assertIn("COM-DASH-0001", commercial_html)
        self.assertIn("COM-DASH-0002", commercial_html)
        self.assertNotIn("TRX-DASH-0001", commercial_html)

        paid_html = self.client.get("/dashboard?recent_filter=Paid").get_data(as_text=True)
        self.assertIn("TRX-DASH-PAID", paid_html)
        self.assertNotIn("COM-DASH-0001", paid_html)

    def test_transactions_page_lists_local_and_commercial_rows(self):
        html = self.client.get("/transactions?type=all").get_data(as_text=True)

        self.assertIn("TRX-DASH-0001", html)
        self.assertIn("COM-DASH-0001", html)
        self.assertIn("Local", html)
        self.assertIn("Commercial", html)
        self.assertIn("100.00 kg", html)
        self.assertIn("2.00 sacks", html)

    def test_transactions_page_has_clickable_type_filters(self):
        html = self.client.get("/transactions?type=all").get_data(as_text=True)

        self.assertIn('href="/transactions?type=local"', html)
        self.assertIn('href="/transactions?type=commercial"', html)

        local_html = self.client.get("/transactions?type=local").get_data(as_text=True)
        self.assertIn("TRX-DASH-0001", local_html)
        self.assertNotIn("COM-DASH-0001", local_html)

        commercial_html = self.client.get("/transactions?type=commercial").get_data(as_text=True)
        self.assertIn("COM-DASH-0001", commercial_html)
        self.assertNotIn("TRX-DASH-0001", commercial_html)

    def test_dashboard_recent_filter_links_return_to_recent_section(self):
        html = self.client.get("/dashboard").get_data(as_text=True)

        self.assertIn('id="recent-transactions"', html)
        self.assertIn("/dashboard?recent_filter=Local#recent-transactions", html)
        self.assertIn("/dashboard?recent_filter=Commercial#recent-transactions", html)
        self.assertIn("/dashboard?recent_filter=Paid#recent-transactions", html)

    def test_mobile_bottom_nav_prioritizes_settings_over_new(self):
        html = self.client.get("/dashboard").get_data(as_text=True)
        bottom_nav = re.search(r'<nav class="bottom-nav">(?P<nav>.*?)</nav>', html, flags=re.S)

        self.assertIsNotNone(bottom_nav)
        mobile_nav = bottom_nav.group("nav")
        self.assertIn('href="/settings"', mobile_nav)
        self.assertIn(">Settings</a>", mobile_nav)
        self.assertNotIn(">New</a>", mobile_nav)

    def test_dashboard_nav_uses_palaykita_logo_image(self):
        html = self.client.get("/dashboard").get_data(as_text=True)
        brand = re.search(r'<a class="brand"[^>]*>(?P<brand>.*?)</a>', html, flags=re.S)

        self.assertIsNotNone(brand)
        brand_markup = brand.group("brand")
        self.assertIn('/static/icons/palaykita_logo.png', brand_markup)
        self.assertIn('alt="PalayKita logo"', brand_markup)
        self.assertNotIn(">PK</span>", brand_markup)

    def test_dashboard_nav_wordmark_matches_login_colors(self):
        html = self.client.get("/dashboard").get_data(as_text=True)

        self.assertIn('class="brand-wordmark"', html)
        self.assertIn('class="word-palay">Palay</span>', html)
        self.assertIn('class="word-kita">Kita</span>', html)
        self.assertIn("color: #D69C0B;", Path("static/css/app.css").read_text())
        self.assertIn("color: #056C27;", Path("static/css/app.css").read_text())
        self.assertIn("<small>Dashboard Mill</small>", html)

    def test_dashboard_brand_text_sits_close_to_logo(self):
        css = Path("static/css/app.css").read_text()

        self.assertRegex(css, r"\.brand\s*\{[^}]*gap:\s*6px;", msg="Navbar brand gap should keep text close to the logo.")


if __name__ == "__main__":
    unittest.main()
