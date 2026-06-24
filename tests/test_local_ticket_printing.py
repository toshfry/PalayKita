import unittest
from datetime import date, timedelta
from decimal import Decimal

from flask import Flask

from app import db
from app.models import CommercialCustomer, MillingTransaction, Setting, User, AuditLog
from app.utils import local_ticket_number


class LocalTicketPrintingTests(unittest.TestCase):
    def setUp(self):
        import app.routes as routes

        routes.is_activated = lambda: True
        self.app = Flask(__name__, template_folder="../templates", static_folder="../static")
        self.app.config.update(
            SECRET_KEY="local-ticket-test",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
        )
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

        self.user = User(username="admin", password_hash="x", role="admin", is_active=True)
        self.settings = Setting()
        db.session.add_all([self.user, self.settings])
        db.session.commit()

        self.app.register_blueprint(routes.main_bp)
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user.id
            session["username"] = self.user.username
            session["role"] = self.user.role

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def _save_local(self, customer_name="", kilos="120", rate="2.50",
                    transaction_date=None):
        return self.client.post(
            "/transactions/new",
            data={
                "transaction_type": "local",
                "transaction_date": (transaction_date or date.today()).strftime("%Y-%m-%d"),
                "customer_name": customer_name,
                "contact_number": "",
                "kilos_milled": kilos,
                "milling_rate_per_kg": rate,
                "amount_paid": "0",
                "has_chaff_deduction": "no",
                "chaff_kilos": "0",
                "chaff_rate_per_kg": "0",
                "payment_method": "Cash",
            },
        )

    # --- defaults -------------------------------------------------------

    def test_ticket_settings_have_expected_defaults(self):
        settings = Setting.query.first()
        self.assertTrue(settings.ticket_printing_enabled)
        self.assertTrue(settings.ticket_show_after_save)
        self.assertEqual(settings.ticket_paper_size, "80mm")
        self.assertEqual(settings.ticket_mill_name, "Arman Rice Mill")
        self.assertEqual(settings.ticket_footer_message, "Please present this ticket when paying.")

    # --- save flow ------------------------------------------------------

    def test_local_save_redirects_with_saved_ticket_and_shows_button(self):
        response = self._save_local()
        self.assertEqual(response.status_code, 302)
        self.assertIn("type=local", response.location)
        self.assertIn("saved_ticket=", response.location)

        html = self.client.get(response.location).get_data(as_text=True)
        self.assertIn("Print Ticket", html)
        self.assertIn('id="ticketPrintBanner"', html)
        self.assertIn("Transaction saved successfully.", html)
        # Form reset for next customer.
        self.assertIn('name="kilos_milled" id="kilos" value=""', html)

    def test_button_hidden_when_show_after_save_is_off(self):
        self.settings.ticket_show_after_save = False
        db.session.commit()

        response = self._save_local()
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("saved_ticket=", response.location)
        html = self.client.get(response.location).get_data(as_text=True)
        self.assertNotIn('id="ticketPrintBanner"', html)

    # --- ticket number --------------------------------------------------

    def test_ticket_number_matches_customer_no(self):
        response = self._save_local(customer_name="")
        trx = MillingTransaction.query.one()
        self.assertEqual(trx.customer_name, "Customer No. 1")
        self.assertEqual(local_ticket_number(trx), 1)

    def test_edited_name_uses_daily_sequence(self):
        self._save_local(customer_name="")               # Customer No. 1
        self._save_local(customer_name="Juan Dela Cruz")  # edited -> seq 2
        edited = MillingTransaction.query.filter_by(customer_name="Juan Dela Cruz").one()
        self.assertEqual(local_ticket_number(edited), 2)

    def test_ticket_number_resets_next_day(self):
        today = date.today()
        yesterday = today - timedelta(days=1)
        self._save_local(customer_name="", transaction_date=yesterday)  # No. 1 yesterday
        self._save_local(customer_name="", transaction_date=today)      # No. 1 today

        first_today = MillingTransaction.query.filter_by(
            transaction_date=today, customer_name="Customer No. 1"
        ).one()
        self.assertEqual(local_ticket_number(first_today), 1)

    # --- ticket content -------------------------------------------------

    def test_ticket_shows_only_allowed_fields(self):
        self._save_local(customer_name="", kilos="120", rate="2.50")
        trx = MillingTransaction.query.one()
        html = self.client.get(f"/transactions/{trx.id}/ticket").get_data(as_text=True)

        self.assertIn("PALAYKITA", html)
        self.assertIn("Arman Rice Mill", html)
        self.assertIn("LOCAL TRANSACTION TICKET #1", html)
        self.assertIn("Ref No.", html)
        self.assertIn(trx.transaction_number, html)
        self.assertIn("120.00 kg", html)
        self.assertIn("PHP 2.50", html)
        self.assertIn("PHP 300.00", html)
        self.assertIn("Please present this ticket", html)
        self.assertIn("window.print()", html)

        for forbidden in ["Balance", "Amount Paid", "Status", "Payment Method",
                          "Notes", "Chaff", "Commercial"]:
            self.assertNotIn(forbidden, html)

    def test_ticket_shows_transaction_number_reference(self):
        self._save_local(customer_name="")
        trx = MillingTransaction.query.one()
        html = self.client.get(f"/transactions/{trx.id}/ticket").get_data(as_text=True)
        # Daily Customer No. stays the headline; the unique transaction number is
        # printed as a reference for unambiguous pay-later lookup.
        self.assertIn("LOCAL TRANSACTION TICKET #1", html)
        self.assertIn(f"Ref No. : {trx.transaction_number}", html)

    def test_ticket_route_blocked_when_printing_disabled(self):
        self._save_local()
        trx = MillingTransaction.query.one()
        self.settings.ticket_printing_enabled = False
        db.session.commit()

        response = self.client.get(f"/transactions/{trx.id}/ticket")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/transactions/new", response.location)

    # --- commercial isolation -------------------------------------------

    def test_commercial_save_has_no_print_ticket(self):
        customer = CommercialCustomer(name="Test Trading", status="Active")
        db.session.add(customer)
        db.session.commit()

        response = self.client.post(
            "/transactions/new",
            data={
                "transaction_type": "commercial",
                "transaction_date": date.today().strftime("%Y-%m-%d"),
                "commercial_customer_id": str(customer.id),
                "number_of_sacks": "10",
                "price_per_sack": "100",
                "amount_paid": "0",
                "payment_method": "Cash",
                "payment_status": "Unpaid",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("saved_ticket=", response.location)
        html = self.client.get(response.location).get_data(as_text=True)
        self.assertNotIn('id="ticketPrintBanner"', html)

    # --- settings tools + audit -----------------------------------------

    def test_test_ticket_and_reprint_and_audit(self):
        self._save_local()
        trx = MillingTransaction.query.one()

        self.client.get(f"/transactions/{trx.id}/ticket")
        self.client.get(f"/transactions/{trx.id}/ticket?reprint=1")
        sample = self.client.get("/settings/ticket/test").get_data(as_text=True)
        self.assertIn("LOCAL TRANSACTION TICKET #30", sample)
        self.assertIn("Ref No. : TRX-20260621-0001", sample)

        actions = {row.action for row in AuditLog.query.all()}
        self.assertIn("Print Local Ticket", actions)
        self.assertIn("Reprint Local Ticket", actions)
        self.assertIn("Test Local Ticket", actions)


if __name__ == "__main__":
    unittest.main()
