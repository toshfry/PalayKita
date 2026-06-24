import unittest
from decimal import Decimal

from flask import Flask

from app import db
from app.calculations import compute_commercial_transaction, money
from app.models import AuditLog, CommercialCustomer, CommercialTransaction, MillingTransaction, Setting, User


class CommercialCalculationTests(unittest.TestCase):
    def test_commercial_transaction_is_computed_per_sack(self):
        result = compute_commercial_transaction(
            number_of_sacks="12",
            price_per_sack="1450.50",
            amount_paid="10000",
        )

        self.assertEqual(result["number_of_sacks"], Decimal("12.00"))
        self.assertEqual(result["price_per_sack"], Decimal("1450.50"))
        self.assertEqual(result["total_amount"], Decimal("17406.00"))
        self.assertEqual(result["amount_paid"], Decimal("10000.00"))
        self.assertEqual(result["balance"], Decimal("7406.00"))
        self.assertEqual(result["payment_status"], "Partial")

    def test_commercial_transaction_marks_paid_when_amount_covers_total(self):
        result = compute_commercial_transaction(
            number_of_sacks="5",
            price_per_sack="1000",
            amount_paid="6000",
        )

        self.assertEqual(result["total_amount"], Decimal("5000.00"))
        self.assertEqual(result["balance"], money(0))
        self.assertEqual(result["payment_status"], "Paid")

    def test_commercial_transaction_marks_unpaid_without_payment(self):
        result = compute_commercial_transaction(
            number_of_sacks="3",
            price_per_sack="1200",
            amount_paid="0",
        )

        self.assertEqual(result["total_amount"], Decimal("3600.00"))
        self.assertEqual(result["balance"], Decimal("3600.00"))
        self.assertEqual(result["payment_status"], "Unpaid")


class CommercialModelTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SECRET_KEY="test",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def test_commercial_customer_stores_contact_details_separately(self):
        customer = CommercialCustomer(
            name="Golden Grain Trading",
            contact_number="09171234567",
            address="Nueva Ecija",
            notes="Pays every Friday",
            status="Active",
        )

        db.session.add(customer)
        db.session.commit()

        saved = CommercialCustomer.query.one()
        self.assertEqual(saved.name, "Golden Grain Trading")
        self.assertEqual(saved.status, "Active")
        self.assertTrue(saved.is_active)

    def test_commercial_transaction_belongs_to_registered_customer(self):
        customer = CommercialCustomer(name="Rice Hub", status="Active")
        db.session.add(customer)
        db.session.flush()

        transaction = CommercialTransaction(
            transaction_number="COM-20260619-0001",
            customer_id=customer.id,
            number_of_sacks=Decimal("10.00"),
            price_per_sack=Decimal("1500.00"),
            total_amount=Decimal("15000.00"),
            amount_paid=Decimal("5000.00"),
            balance=Decimal("10000.00"),
            payment_status="Partial",
        )

        db.session.add(transaction)
        db.session.commit()

        saved = CommercialTransaction.query.one()
        self.assertEqual(saved.customer.name, "Rice Hub")
        self.assertEqual(customer.commercial_transactions[0].transaction_number, "COM-20260619-0001")

    def test_settings_include_commercial_defaults(self):
        settings = Setting()
        db.session.add(settings)
        db.session.commit()

        saved = Setting.query.one()
        self.assertTrue(saved.commercial_enabled)
        self.assertEqual(saved.commercial_default_payment_status, "Unpaid")
        self.assertEqual(saved.commercial_receipt_label, "Commercial Transaction")


class CommercialRouteTests(unittest.TestCase):
    def setUp(self):
        import app.routes as routes

        routes.is_activated = lambda: True
        self.app = Flask(
            __name__,
            template_folder="../templates",
            static_folder="../static",
        )
        self.app.config.update(
            SECRET_KEY="test",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
        )
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

        user = User(username="admin", password_hash="test", role="admin", is_active=True)
        settings = Setting()
        db.session.add_all([user, settings])
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

    def test_commercial_transaction_requires_registered_customer(self):
        response = self.client.post(
            "/transactions/new",
            data={
                "transaction_type": "commercial",
                "commercial_customer_id": "",
                "number_of_sacks": "10",
                "price_per_sack": "1500",
                "amount_paid": "0",
                "transaction_date": "2026-06-19",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(CommercialTransaction.query.count(), 0)
        self.assertEqual(MillingTransaction.query.count(), 0)

    def test_commercial_transaction_saves_against_active_customer(self):
        customer = CommercialCustomer(name="Golden Grain Trading", status="Active")
        db.session.add(customer)
        db.session.commit()

        response = self.client.post(
            "/transactions/new",
            data={
                "transaction_type": "commercial",
                "commercial_customer_id": str(customer.id),
                "number_of_sacks": "4",
                "price_per_sack": "1200",
                "amount_paid": "1000",
                "transaction_date": "2026-06-19",
                "notes": "Deliver Friday",
            },
        )

        self.assertEqual(response.status_code, 302)
        saved = CommercialTransaction.query.one()
        self.assertEqual(saved.customer_id, customer.id)
        self.assertEqual(saved.total_amount, Decimal("4800.00"))
        self.assertEqual(saved.balance, Decimal("3800.00"))
        self.assertEqual(saved.payment_status, "Partial")
        self.assertEqual(MillingTransaction.query.count(), 0)

    def test_commercial_transactions_get_unique_numbers_when_dated_off_today(self):
        # Regression: the daily number prefix uses date.today(), but the
        # sequence search must not be scoped by the user-picked transaction_date.
        # Two transactions saved today with a non-today date must still receive
        # distinct transaction_numbers instead of colliding on the UNIQUE column.
        customer = CommercialCustomer(name="Golden Grain Trading", status="Active")
        db.session.add(customer)
        db.session.commit()

        payload = {
            "transaction_type": "commercial",
            "commercial_customer_id": str(customer.id),
            "number_of_sacks": "4",
            "price_per_sack": "1200",
            "amount_paid": "0",
            "transaction_date": "2027-06-20",
        }

        first = self.client.post("/transactions/new", data=payload)
        self.assertEqual(first.status_code, 302)

        second = self.client.post("/transactions/new", data=payload)
        self.assertEqual(second.status_code, 302)

        numbers = {t.transaction_number for t in CommercialTransaction.query.all()}
        self.assertEqual(CommercialTransaction.query.count(), 2)
        self.assertEqual(len(numbers), 2)

    def test_commercial_transaction_returns_to_new_commercial_form_after_save(self):
        customer = CommercialCustomer(name="Golden Grain Trading", status="Active")
        db.session.add(customer)
        db.session.commit()

        response = self.client.post(
            "/transactions/new",
            data={
                "transaction_type": "commercial",
                "commercial_customer_id": str(customer.id),
                "number_of_sacks": "4",
                "price_per_sack": "1200",
                "amount_paid": "1000",
                "transaction_date": "2026-06-19",
                "notes": "Deliver Friday",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/transactions/new?type=commercial"))

        html = self.client.get(response.location).get_data(as_text=True)
        self.assertIn("Commercial transaction saved successfully.", html)
        self.assertIn('id="transactionType" value="commercial"', html)
        self.assertIn("Select registered customer", html)
        self.assertNotIn(f'value="{customer.id}" selected', html)
        self.assertIn('name="number_of_sacks"', html)
        self.assertIn('id="commercialSacks"', html)
        self.assertEqual(MillingTransaction.query.count(), 0)

    def test_inactive_commercial_customer_is_not_selectable_for_new_transaction(self):
        active = CommercialCustomer(name="Active Buyer", status="Active")
        inactive = CommercialCustomer(name="Inactive Buyer", status="Inactive")
        db.session.add_all([active, inactive])
        db.session.commit()

        html = self.client.get("/transactions/new?type=commercial").get_data(as_text=True)

        self.assertIn("Active Buyer", html)
        self.assertNotIn("Inactive Buyer", html)

    def test_commercial_customer_delete_and_deactivate_are_separate_actions(self):
        customer = CommercialCustomer(name="No History Buyer", status="Active")
        history_customer = CommercialCustomer(name="History Buyer", status="Active")
        db.session.add_all([customer, history_customer])
        db.session.flush()
        db.session.add(CommercialTransaction(
            transaction_number="COM-20260619-0001",
            customer_id=history_customer.id,
            number_of_sacks=Decimal("2.00"),
            price_per_sack=Decimal("1000.00"),
            total_amount=Decimal("2000.00"),
            amount_paid=Decimal("0.00"),
            balance=Decimal("2000.00"),
            payment_status="Unpaid",
        ))
        db.session.commit()

        delete_response = self.client.post(f"/commercial-customers/{customer.id}/delete")
        deactivate_response = self.client.post(f"/commercial-customers/{history_customer.id}/deactivate")

        self.assertEqual(delete_response.status_code, 302)
        self.assertEqual(deactivate_response.status_code, 302)
        self.assertIsNone(db.session.get(CommercialCustomer, customer.id))
        self.assertEqual(db.session.get(CommercialCustomer, history_customer.id).status, "Inactive")
        actions = [row.action for row in AuditLog.query.order_by(AuditLog.id).all()]
        self.assertIn("Delete Commercial Customer", actions)
        self.assertIn("Deactivate Commercial Customer", actions)

    def test_reactivate_commercial_customer_restores_active_status_and_logs(self):
        customer = CommercialCustomer(name="Dormant Buyer", status="Inactive")
        db.session.add(customer)
        db.session.commit()

        response = self.client.post(f"/commercial-customers/{customer.id}/reactivate")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(db.session.get(CommercialCustomer, customer.id).status, "Active")
        log = AuditLog.query.order_by(AuditLog.id.desc()).first()
        self.assertEqual(log.action, "Reactivate Commercial Customer")
        self.assertIn("Dormant Buyer", log.details)

    def test_commercial_customer_page_has_separate_delete_deactivate_and_reactivate_controls(self):
        active = CommercialCustomer(name="Active Buyer", status="Active")
        inactive = CommercialCustomer(name="Inactive Buyer", status="Inactive")
        db.session.add_all([active, inactive])
        db.session.commit()

        html = self.client.get("/commercial-customers").get_data(as_text=True)

        self.assertIn(f"/commercial-customers/{active.id}/delete", html)
        self.assertIn(f"/commercial-customers/{active.id}/deactivate", html)
        self.assertIn(f"/commercial-customers/{inactive.id}/reactivate", html)
        self.assertNotIn("Delete / Deactivate", html)

    def test_commercial_transaction_edit_recalculates_and_logs_before_after_values(self):
        customer = CommercialCustomer(name="Golden Grain Trading", status="Active")
        other_customer = CommercialCustomer(name="Other Buyer", status="Active")
        db.session.add_all([customer, other_customer])
        db.session.flush()
        transaction = CommercialTransaction(
            transaction_number="COM-EDIT-0001",
            customer_id=customer.id,
            number_of_sacks=Decimal("5.00"),
            price_per_sack=Decimal("1000.00"),
            total_amount=Decimal("5000.00"),
            amount_paid=Decimal("1000.00"),
            balance=Decimal("4000.00"),
            payment_status="Partial",
            notes="Original note",
        )
        db.session.add(transaction)
        db.session.commit()

        response = self.client.post(
            f"/commercial-transactions/{transaction.id}/edit",
            data={
                "transaction_date": "2026-06-20",
                "commercial_customer_id": str(other_customer.id),
                "number_of_sacks": "4",
                "price_per_sack": "1200",
                "total_amount": "4800",
                "amount_paid": "4800",
                "payment_method": "GCash",
                "notes": "Corrected amount",
                "payment_status": "Unpaid",
            },
        )

        self.assertEqual(response.status_code, 302)
        saved = db.session.get(CommercialTransaction, transaction.id)
        self.assertEqual(saved.customer_id, customer.id)
        self.assertEqual(saved.number_of_sacks, Decimal("4.00"))
        self.assertEqual(saved.price_per_sack, Decimal("1200.00"))
        self.assertEqual(saved.total_amount, Decimal("4800.00"))
        self.assertEqual(saved.amount_paid, Decimal("4800.00"))
        self.assertEqual(saved.balance, Decimal("0.00"))
        self.assertEqual(saved.payment_status, "Paid")
        self.assertEqual(saved.payment_method, "GCash")
        self.assertEqual(saved.notes, "Corrected amount")

        log = AuditLog.query.order_by(AuditLog.id.desc()).first()
        self.assertEqual(log.action, "Edit Commercial Transaction")
        self.assertIn("COM-EDIT-0001", log.details)
        self.assertIn("Total:", log.details)
        self.assertIn("5,000.00", log.details)
        self.assertIn("4,800.00", log.details)
        self.assertIn("Paid:", log.details)
        self.assertIn("Balance:", log.details)
        self.assertIn("Status: Partial -> Paid", log.details)

    def test_commercial_transaction_edit_links_show_on_transaction_pages(self):
        customer = CommercialCustomer(name="Golden Grain Trading", status="Active")
        db.session.add(customer)
        db.session.flush()
        transaction = CommercialTransaction(
            transaction_number="COM-EDIT-LINK",
            customer_id=customer.id,
            number_of_sacks=Decimal("2.00"),
            price_per_sack=Decimal("1000.00"),
            total_amount=Decimal("2000.00"),
            amount_paid=Decimal("0.00"),
            balance=Decimal("2000.00"),
            payment_status="Unpaid",
        )
        db.session.add(transaction)
        db.session.commit()

        transactions_html = self.client.get("/transactions?type=commercial").get_data(as_text=True)
        detail_html = self.client.get(f"/commercial-customers/{customer.id}").get_data(as_text=True)

        edit_path = f"/commercial-transactions/{transaction.id}/edit"
        self.assertIn(edit_path, transactions_html)
        self.assertIn(edit_path, detail_html)

    def test_commercial_transaction_edit_page_renders_commercial_fields(self):
        customer = CommercialCustomer(name="Golden Grain Trading", status="Active")
        db.session.add(customer)
        db.session.flush()
        transaction = CommercialTransaction(
            transaction_number="COM-EDIT-FORM",
            customer_id=customer.id,
            number_of_sacks=Decimal("2.00"),
            price_per_sack=Decimal("1000.00"),
            total_amount=Decimal("2000.00"),
            amount_paid=Decimal("500.00"),
            balance=Decimal("1500.00"),
            payment_status="Partial",
            payment_method="Cash",
            notes="Needs correction",
        )
        db.session.add(transaction)
        db.session.commit()

        html = self.client.get(f"/commercial-transactions/{transaction.id}/edit").get_data(as_text=True)

        self.assertIn("Edit Commercial Transaction", html)
        self.assertIn("Golden Grain Trading", html)
        self.assertIn('id="commercialTotalAmount"', html)
        self.assertIn('name="payment_method"', html)
        self.assertIn('id="commercialPaymentStatus"', html)
        self.assertNotIn("Customer / Owner Name", html.split('data-txn-section="commercial"')[1])


if __name__ == "__main__":
    unittest.main()
