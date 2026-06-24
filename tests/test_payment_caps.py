import unittest
from datetime import date
from decimal import Decimal

from flask import Flask

from app import db
from app.models import CommercialCustomer, CommercialTransaction, CommercialPayment, MillingTransaction, Setting, User
from app.calculations import compute_transaction, compute_commercial_transaction


class OverpaymentCapTests(unittest.TestCase):
    def setUp(self):
        import app.routes as routes

        routes.is_activated = lambda: True
        self.app = Flask(__name__, template_folder="../templates", static_folder="../static")
        self.app.config.update(
            SECRET_KEY="payment-cap-test",
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
        self.customer = CommercialCustomer(name="Cap Trading", status="Active")
        db.session.add_all([self.user, self.settings, self.customer])
        db.session.commit()
        self.customer_id = self.customer.id

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

    # --- calculation-level caps (create / edit) -------------------------

    def test_compute_transaction_caps_amount_paid_to_net(self):
        result = compute_transaction(kilos_milled="100", milling_rate_per_kg="3", amount_paid="99999")
        self.assertEqual(result["net_amount"], Decimal("300.00"))
        self.assertEqual(result["amount_paid"], Decimal("300.00"))
        self.assertEqual(result["balance"], Decimal("0.00"))
        self.assertEqual(result["payment_status"], "Paid")

    def test_compute_commercial_caps_amount_paid_to_total(self):
        result = compute_commercial_transaction(number_of_sacks="10", price_per_sack="100", amount_paid="50000")
        self.assertEqual(result["total_amount"], Decimal("1000.00"))
        self.assertEqual(result["amount_paid"], Decimal("1000.00"))
        self.assertEqual(result["balance"], Decimal("0.00"))

    # --- route-level caps (recording payments) --------------------------

    def _make_unpaid_local(self):
        self.client.post("/transactions/new", data={
            "transaction_type": "local", "transaction_date": date.today().strftime("%Y-%m-%d"),
            "customer_name": "", "kilos_milled": "100", "milling_rate_per_kg": "3",
            "amount_paid": "0", "has_chaff_deduction": "no", "payment_method": "Cash",
        })
        return MillingTransaction.query.order_by(MillingTransaction.id.desc()).first()

    def test_record_payment_caps_to_balance(self):
        trx = self._make_unpaid_local()
        self.client.post(f"/transactions/{trx.id}/payment", data={"payment_amount": "99999", "payment_method": "Cash"})
        trx = db.session.get(MillingTransaction, trx.id)
        self.assertEqual(trx.amount_paid, Decimal("300.00"))
        self.assertEqual(trx.balance, Decimal("0.00"))
        self.assertEqual(trx.payment_status, "Paid")

    def test_record_payment_blocks_when_already_paid(self):
        trx = self._make_unpaid_local()
        self.client.post(f"/transactions/{trx.id}/payment", data={"payment_amount": "300", "payment_method": "Cash"})
        self.client.post(f"/transactions/{trx.id}/payment", data={"payment_amount": "100", "payment_method": "Cash"})
        trx = db.session.get(MillingTransaction, trx.id)
        self.assertEqual(trx.amount_paid, Decimal("300.00"))  # second payment not applied

    def test_record_commercial_payment_caps_to_balance(self):
        self.client.post("/transactions/new", data={
            "transaction_type": "commercial", "transaction_date": date.today().strftime("%Y-%m-%d"),
            "commercial_customer_id": str(self.customer_id), "number_of_sacks": "10",
            "price_per_sack": "100", "amount_paid": "0", "payment_method": "Cash", "payment_status": "Unpaid",
        })
        ct = CommercialTransaction.query.order_by(CommercialTransaction.id.desc()).first()
        self.client.post(f"/commercial-transactions/{ct.id}/payment", data={"payment_amount": "50000", "payment_method": "Cash"})
        ct = db.session.get(CommercialTransaction, ct.id)
        self.assertEqual(ct.amount_paid, Decimal("1000.00"))
        self.assertEqual(ct.balance, Decimal("0.00"))

    # --- server-side quantity validation --------------------------------

    def test_zero_kilo_local_rejected_server_side(self):
        before = MillingTransaction.query.count()
        resp = self.client.post("/transactions/new", data={
            "transaction_type": "local", "transaction_date": date.today().strftime("%Y-%m-%d"),
            "customer_name": "", "kilos_milled": "0", "milling_rate_per_kg": "3",
            "amount_paid": "0", "has_chaff_deduction": "no", "payment_method": "Cash",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(MillingTransaction.query.count(), before)  # nothing saved

    def test_negative_kilo_local_rejected_server_side(self):
        before = MillingTransaction.query.count()
        self.client.post("/transactions/new", data={
            "transaction_type": "local", "transaction_date": date.today().strftime("%Y-%m-%d"),
            "customer_name": "", "kilos_milled": "-50", "milling_rate_per_kg": "3",
            "amount_paid": "0", "has_chaff_deduction": "no", "payment_method": "Cash",
        })
        self.assertEqual(MillingTransaction.query.count(), before)  # nothing saved

    # --- commercial payment ledger (ISSUE-010) --------------------------

    def _make_unpaid_commercial(self):
        self.client.post("/transactions/new", data={
            "transaction_type": "commercial", "transaction_date": date.today().strftime("%Y-%m-%d"),
            "commercial_customer_id": str(self.customer_id), "number_of_sacks": "10",
            "price_per_sack": "100", "amount_paid": "0", "payment_method": "Cash", "payment_status": "Unpaid",
        })
        return CommercialTransaction.query.order_by(CommercialTransaction.id.desc()).first()

    def test_commercial_payment_records_ledger_row(self):
        ct = self._make_unpaid_commercial()
        self.client.post(f"/commercial-transactions/{ct.id}/payment",
                         data={"payment_amount": "400", "payment_method": "GCash", "payment_notes": "deposit"})
        rows = CommercialPayment.query.filter_by(transaction_id=ct.id).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].amount, Decimal("400.00"))
        self.assertEqual(rows[0].payment_method, "GCash")
        # history is shown on the customer detail page
        html = self.client.get(f"/commercial-customers/{self.customer_id}").get_data(as_text=True)
        self.assertIn("Payment History", html)

    def test_mark_commercial_paid_records_ledger_row(self):
        ct = self._make_unpaid_commercial()
        self.client.post(f"/commercial-transactions/{ct.id}/mark-paid", data={})
        rows = CommercialPayment.query.filter_by(transaction_id=ct.id).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].amount, Decimal("1000.00"))


if __name__ == "__main__":
    unittest.main()
