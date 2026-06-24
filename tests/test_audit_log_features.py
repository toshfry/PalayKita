import unittest
import re
import shutil
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from flask import Flask, session
from openpyxl import load_workbook

from app import db
from app.models import AuditLog, MillingTransaction, Setting, User
from app.utils import log_action


class AuditLogFeatureTests(unittest.TestCase):
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

        root = Path.cwd() / "exports" / "_test_audit_log_features" / uuid.uuid4().hex
        root.mkdir(parents=True, exist_ok=True)
        self.export_root = root
        self.app = Flask(__name__, template_folder="../templates", static_folder="../static")
        self.app.config.update(
            SECRET_KEY="audit-log-test",
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

        self.staff_user = User(
            username="staff1",
            full_name="John Lloyd Sereno",
            password_hash="x",
            role="staff",
            is_active=True,
        )
        self.admin_user = User(
            username="admin",
            full_name="Owner Admin",
            password_hash="x",
            role="admin",
            is_active=True,
        )
        db.session.add_all([Setting(business_name="Audit Test Mill"), self.staff_user, self.admin_user])
        db.session.commit()

        self.app.register_blueprint(routes.main_bp)
        self.client = self.app.test_client()
        with self.client.session_transaction() as client_session:
            client_session["user_id"] = self.admin_user.id
            client_session["username"] = self.admin_user.username
            client_session["role"] = self.admin_user.role

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()
        shutil.rmtree(self.export_root, ignore_errors=True)

    def test_log_action_snapshots_full_name_username_and_role(self):
        with self.app.test_request_context("/"):
            session["user_id"] = self.staff_user.id
            session["username"] = self.staff_user.username
            session["role"] = self.staff_user.role
            log_action("Delete Transaction", "Deleted TRX-20260619-0003")

        log = AuditLog.query.one()

        self.assertEqual(log.user_full_name, "John Lloyd Sereno")
        self.assertEqual(log.username, "staff1")
        self.assertEqual(log.user_role, "staff")
        self.assertEqual(log.action, "Delete Transaction")

    def test_edit_local_transaction_records_before_and_after_values(self):
        trx = MillingTransaction(
            transaction_number="TRX-20260101-0001",
            customer_name="Mang Juan",
            kilos_milled=Decimal("100.00"),
            milling_rate_per_kg=Decimal("2.50"),
            gross_fee=Decimal("250.00"),
            has_chaff_deduction=False,
            chaff_kilos=Decimal("0.00"),
            chaff_rate_per_kg=Decimal("0.00"),
            chaff_deduction=Decimal("0.00"),
            net_amount=Decimal("250.00"),
            amount_paid=Decimal("0.00"),
            balance=Decimal("250.00"),
            payment_status="Unpaid",
            payment_method="Cash",
            transaction_date=date.today(),
        )
        db.session.add(trx)
        db.session.commit()

        response = self.client.post(
            f"/transactions/{trx.id}/edit",
            data={
                "customer_name": "Mang Juan",
                "kilos_milled": "150",
                "milling_rate_per_kg": "3.00",
                "amount_paid": "0",
                "has_chaff_deduction": "no",
                "chaff_kilos": "0",
                "chaff_rate_per_kg": "0",
                "payment_method": "Cash",
                "transaction_date": date.today().strftime("%Y-%m-%d"),
            },
        )

        self.assertEqual(response.status_code, 302)

        log = AuditLog.query.filter_by(action="Edit Transaction").one()
        self.assertIn("Edited TRX-20260101-0001", log.details)
        # Original -> edited kilos and price/rate are captured
        self.assertIn("Kilos: 100.00 kg -> 150.00 kg", log.details)
        self.assertIn("Rate/Kilo:", log.details)
        self.assertIn("2.50", log.details)
        self.assertIn("3.00", log.details)
        # Unchanged customer should not appear as a change line
        self.assertNotIn("Customer: Mang Juan -> Mang Juan", log.details)

    def test_settings_shows_audit_log_with_date_time_and_full_name(self):
        today = date.today()
        log = AuditLog(
            user_id=self.staff_user.id,
            user_full_name="John Lloyd Sereno",
            username="staff1",
            user_role="staff",
            action="Delete Transaction",
            details="Deleted TRX-20260619-0003 | Customer: Walk-in | Total: P187.50",
            created_at=datetime.combine(today, datetime.strptime("22:45", "%H:%M").time()),
        )
        db.session.add(log)
        db.session.commit()

        html = self.client.get("/settings").get_data(as_text=True)
        expected_timestamp = f"{today.strftime('%Y-%m-%d')} 10:45 PM"

        self.assertIn('href="#audit-log"', html)
        self.assertIn("Audit Log", html)
        self.assertIn("John Lloyd Sereno", html)
        self.assertIn("@staff1", html)
        self.assertIn("Staff", html)
        self.assertIn("Delete Transaction", html)
        self.assertIn(expected_timestamp, html)
        self.assertIn("Deleted TRX-20260619-0003", html)
        self.assertIn("/settings/audit-log/export", html)

    def test_settings_defaults_audit_log_date_range_to_today(self):
        today = date.today()
        yesterday = today - timedelta(days=1)
        db.session.add_all([
            AuditLog(
                user_id=self.staff_user.id,
                user_full_name="John Lloyd Sereno",
                username="staff1",
                user_role="staff",
                action="Today Action",
                details="Shown by default",
                created_at=datetime.combine(today, datetime.strptime("09:00", "%H:%M").time()),
            ),
            AuditLog(
                user_id=self.staff_user.id,
                user_full_name="John Lloyd Sereno",
                username="staff1",
                user_role="staff",
                action="Yesterday Action",
                details="Hidden by default",
                created_at=datetime.combine(yesterday, datetime.strptime("09:00", "%H:%M").time()),
            ),
        ])
        db.session.commit()

        html = self.client.get("/settings").get_data(as_text=True)
        audit_section = re.search(
            r'<section class="settings-panel audit-log-panel" id="audit-log">(?P<section>.*?)</section>',
            html,
            flags=re.S,
        )

        self.assertIsNotNone(audit_section)
        section = audit_section.group("section")
        audit_rows = re.search(r"<tbody>(?P<rows>.*?)</tbody>", section, flags=re.S)
        self.assertIn(f'name="audit_start" value="{today.strftime("%Y-%m-%d")}"', section)
        self.assertIn(f'name="audit_end" value="{today.strftime("%Y-%m-%d")}"', section)
        self.assertIsNotNone(audit_rows)
        self.assertIn("Today Action", audit_rows.group("rows"))
        self.assertNotIn("Yesterday Action", audit_rows.group("rows"))

    def test_settings_uses_user_id_for_older_audit_rows_without_snapshots(self):
        today = date.today()
        log = AuditLog(
            user_id=self.staff_user.id,
            action="Delete Transaction",
            details="Deleted legacy row",
            created_at=datetime.combine(today, datetime.strptime("22:45", "%H:%M").time()),
        )
        db.session.add(log)
        db.session.commit()

        html = self.client.get("/settings").get_data(as_text=True)
        audit_section = re.search(
            r'<section class="settings-panel audit-log-panel" id="audit-log">(?P<section>.*?)</section>',
            html,
            flags=re.S,
        )

        self.assertIsNotNone(audit_section)
        self.assertIn("John Lloyd Sereno", audit_section.group("section"))
        self.assertIn("@staff1", audit_section.group("section"))
        self.assertIn("Staff", audit_section.group("section"))

    def test_audit_log_exports_to_excel(self):
        today = date.today()
        log = AuditLog(
            user_id=self.staff_user.id,
            user_full_name="John Lloyd Sereno",
            username="staff1",
            user_role="staff",
            action="Delete Transaction",
            details="Deleted TRX-20260619-0003",
            created_at=datetime.combine(today, datetime.strptime("22:45", "%H:%M").time()),
        )
        db.session.add(log)
        db.session.commit()

        response = self.client.get("/settings/audit-log/export")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            response.mimetype,
        )

        workbook = load_workbook(BytesIO(response.data))
        sheet = workbook.active
        self.assertEqual(sheet["A1"].value, "Date & Time")
        self.assertEqual(sheet["B1"].value, "Full Name")
        self.assertEqual(sheet["B2"].value, "John Lloyd Sereno")
        self.assertEqual(sheet["C2"].value, "staff1")
        self.assertEqual(sheet["E2"].value, "Delete Transaction")

    def test_desktop_audit_log_export_prepares_report_and_redirects_to_reports(self):
        import app.routes as routes

        today = date.today()
        log = AuditLog(
            user_id=self.staff_user.id,
            user_full_name="John Lloyd Sereno",
            username="staff1",
            user_role="staff",
            action="Delete Transaction",
            details="Deleted TRX-20260619-0003",
            created_at=datetime.combine(today, datetime.strptime("22:45", "%H:%M").time()),
        )
        db.session.add(log)
        db.session.commit()

        original_desktop_check = routes.is_desktop_request
        routes.is_desktop_request = lambda: True
        self.addCleanup(lambda: setattr(routes, "is_desktop_request", original_desktop_check))

        response = self.client.get("/settings/audit-log/export")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/reports", response.location)
        self.assertIn("audit_report_ready=1", response.location)
        reports = list((Path(self.app.config["EXPORT_DIR"]) / "audit").glob("*.xlsx"))
        self.assertEqual(len(reports), 1)
        self.assertIn("Audit_Log", reports[0].name)

        html = self.client.get(response.location).get_data(as_text=True)
        self.assertIn(
            "Audit Log report is ready for export. Click Export to download the Excel file.",
            html,
        )
        self.assertIn(reports[0].name, html)
        self.assertIn("Export", html)


if __name__ == "__main__":
    unittest.main()
