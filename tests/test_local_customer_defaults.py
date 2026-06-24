import unittest
from datetime import date, timedelta
from decimal import Decimal

from flask import Flask

from app import db
from app.models import CommercialCustomer, CommercialTransaction, MillingTransaction, Setting, User
from app.utils import generate_commercial_transaction_number, generate_transaction_number


class LocalCustomerDefaultTests(unittest.TestCase):
    def setUp(self):
        import app.routes as routes

        routes.is_activated = lambda: True
        self.app = Flask(__name__, template_folder="../templates", static_folder="../static")
        self.app.config.update(
            SECRET_KEY="local-customer-default-test",
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

    def _add_local_transaction(self, number, transaction_date=None, customer_name=None):
        trx = MillingTransaction(
            transaction_number=number,
            customer_name=customer_name or f"Existing {number}",
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
            transaction_date=transaction_date or date.today(),
        )
        db.session.add(trx)
        return trx

    def test_new_local_transaction_defaults_customer_name_to_next_daily_number(self):
        today = date.today()
        self._add_local_transaction("TRX-LOCAL-0001", today)
        self._add_local_transaction("TRX-LOCAL-0002", today)
        self._add_local_transaction("TRX-YESTERDAY-0001", today - timedelta(days=1))

        customer = CommercialCustomer(name="Commercial Buyer", status="Active")
        db.session.add(customer)
        db.session.flush()
        db.session.add(CommercialTransaction(
            transaction_number="COM-LOCAL-0001",
            customer_id=customer.id,
            number_of_sacks=Decimal("2.00"),
            price_per_sack=Decimal("1000.00"),
            total_amount=Decimal("2000.00"),
            amount_paid=Decimal("0.00"),
            balance=Decimal("2000.00"),
            payment_status="Unpaid",
            transaction_date=today,
        ))
        db.session.commit()

        html = self.client.get("/transactions/new").get_data(as_text=True)

        self.assertIn('name="customer_name" value="Customer No. 3"', html)

    def test_local_transaction_saves_default_customer_name_when_unchanged(self):
        response = self.client.post(
            "/transactions/new",
            data={
                "transaction_type": "local",
                "transaction_date": date.today().strftime("%Y-%m-%d"),
                "customer_name": "Customer No. 1",
                "contact_number": "",
                "kilos_milled": "25",
                "milling_rate_per_kg": "5",
                "amount_paid": "125",
                "has_chaff_deduction": "no",
                "chaff_kilos": "0",
                "chaff_rate_per_kg": "0",
                "payment_method": "Cash",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(MillingTransaction.query.one().customer_name, "Customer No. 1")

    def test_local_transaction_returns_to_new_local_form_after_save(self):
        response = self.client.post(
            "/transactions/new",
            data={
                "transaction_type": "local",
                "transaction_date": date.today().strftime("%Y-%m-%d"),
                "customer_name": "Customer No. 1",
                "contact_number": "",
                "kilos_milled": "25",
                "milling_rate_per_kg": "5",
                "amount_paid": "125",
                "has_chaff_deduction": "no",
                "chaff_kilos": "0",
                "chaff_rate_per_kg": "0",
                "payment_method": "Cash",
            },
        )

        self.assertEqual(response.status_code, 302)
        # Stays on the New Transaction (local) form. With local ticket printing
        # enabled by default, the redirect also carries ?saved_ticket=<id> so the
        # Print Ticket button can appear above the form.
        self.assertIn("/transactions/new?type=local", response.location)

        html = self.client.get(response.location).get_data(as_text=True)
        self.assertIn("Transaction saved successfully.", html)
        self.assertIn('id="transactionType" value="local"', html)
        self.assertIn('name="customer_name" value="Customer No. 2"', html)
        self.assertIn('name="kilos_milled" id="kilos" value=""', html)

    def test_local_transaction_saves_custom_customer_name_when_edited(self):
        response = self.client.post(
            "/transactions/new",
            data={
                "transaction_type": "local",
                "transaction_date": date.today().strftime("%Y-%m-%d"),
                "customer_name": "Maria Santos",
                "contact_number": "",
                "kilos_milled": "25",
                "milling_rate_per_kg": "5",
                "amount_paid": "125",
                "has_chaff_deduction": "no",
                "chaff_kilos": "0",
                "chaff_rate_per_kg": "0",
                "payment_method": "Cash",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(MillingTransaction.query.one().customer_name, "Maria Santos")

    def test_commercial_transaction_page_does_not_prefill_local_customer_number(self):
        customer = CommercialCustomer(name="Commercial Buyer", status="Active")
        db.session.add(customer)
        db.session.commit()

        html = self.client.get("/transactions/new?type=commercial").get_data(as_text=True)

        self.assertIn("Select registered customer", html)
        self.assertNotIn('name="customer_name" value="Customer No.', html)

    def test_local_transaction_number_uses_highest_existing_daily_suffix(self):
        today = date.today()
        prefix = today.strftime("%Y%m%d")
        self._add_local_transaction(f"TRX-{prefix}-0004", today)
        db.session.commit()

        self.assertEqual(generate_transaction_number(), f"TRX-{prefix}-0005")

    def test_commercial_transaction_number_uses_highest_existing_daily_suffix(self):
        today = date.today()
        prefix = today.strftime("%Y%m%d")
        customer = CommercialCustomer(name="Commercial Buyer", status="Active")
        db.session.add(customer)
        db.session.flush()
        db.session.add(CommercialTransaction(
            transaction_number=f"COM-{prefix}-0002",
            customer_id=customer.id,
            number_of_sacks=Decimal("2.00"),
            price_per_sack=Decimal("1000.00"),
            total_amount=Decimal("2000.00"),
            amount_paid=Decimal("0.00"),
            balance=Decimal("2000.00"),
            payment_status="Unpaid",
            transaction_date=today,
        ))
        db.session.commit()

        self.assertEqual(generate_commercial_transaction_number(), f"COM-{prefix}-0003")


if __name__ == "__main__":
    unittest.main()
