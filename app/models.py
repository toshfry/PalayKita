from datetime import datetime, date
from app import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(150), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), default="admin", nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(150), default="PalayKita Rice Mill", nullable=False)
    milling_rate_per_kg = db.Column(db.Numeric(12, 2), default=3.00, nullable=False)
    chaff_rate_per_kg = db.Column(db.Numeric(12, 2), default=1.00, nullable=False)
    currency_symbol = db.Column(db.String(10), default="₱", nullable=False)
    receipt_footer = db.Column(db.String(255), default="Thank you for trusting our rice mill.", nullable=False)
    auto_generate_daily_report = db.Column(db.Boolean, default=False, nullable=False)
    daily_report_time = db.Column(db.String(10), default="18:00", nullable=False)
    server_port = db.Column(db.Integer, default=5000, nullable=False)
    commercial_default_price_per_sack = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    commercial_enabled = db.Column(db.Boolean, default=True, nullable=False)
    commercial_default_payment_status = db.Column(db.String(30), default="Unpaid", nullable=False)
    commercial_notes_enabled = db.Column(db.Boolean, default=True, nullable=False)
    commercial_receipt_label = db.Column(db.String(120), default="Commercial Transaction", nullable=False)
    ticket_printing_enabled = db.Column(db.Boolean, default=True, nullable=False)
    ticket_show_after_save = db.Column(db.Boolean, default=True, nullable=False)
    ticket_paper_size = db.Column(db.String(10), default="80mm", nullable=False)
    ticket_mill_name = db.Column(db.String(150), default="Arman Rice Mill", nullable=False)
    ticket_footer_message = db.Column(db.String(255), default="Please present this ticket when paying.", nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class MillingTransaction(db.Model):
    __tablename__ = "milling_transactions"

    id = db.Column(db.Integer, primary_key=True)
    transaction_number = db.Column(db.String(40), unique=True, nullable=False)

    customer_name = db.Column(db.String(150), nullable=True)
    contact_number = db.Column(db.String(50), nullable=True)

    kilos_milled = db.Column(db.Numeric(12, 2), nullable=False)
    milling_rate_per_kg = db.Column(db.Numeric(12, 2), nullable=False)
    gross_fee = db.Column(db.Numeric(12, 2), nullable=False)

    has_chaff_deduction = db.Column(db.Boolean, default=False, nullable=False)
    chaff_kilos = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    chaff_rate_per_kg = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    chaff_deduction = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    net_amount = db.Column(db.Numeric(12, 2), nullable=False)
    amount_paid = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    balance = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    payment_status = db.Column(db.String(30), default="Unpaid", nullable=False)
    payment_method = db.Column(db.String(50), default="Cash", nullable=False)
    notes = db.Column(db.Text, nullable=True)

    transaction_date = db.Column(db.Date, default=date.today, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    payments = db.relationship(
        "Payment",
        backref="transaction",
        cascade="all, delete-orphan",
        lazy=True
    )


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("milling_transactions.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_method = db.Column(db.String(50), default="Cash", nullable=False)
    payment_date = db.Column(db.Date, default=date.today, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)


class CommercialCustomer(db.Model):
    __tablename__ = "commercial_customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    contact_number = db.Column(db.String(50), nullable=True)
    address = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="Active", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    commercial_transactions = db.relationship(
        "CommercialTransaction",
        backref="customer",
        lazy=True,
    )

    @property
    def is_active(self):
        return self.status == "Active"


class CommercialTransaction(db.Model):
    __tablename__ = "commercial_transactions"

    id = db.Column(db.Integer, primary_key=True)
    transaction_number = db.Column(db.String(40), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("commercial_customers.id"), nullable=False)

    number_of_sacks = db.Column(db.Numeric(12, 2), nullable=False)
    price_per_sack = db.Column(db.Numeric(12, 2), nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    amount_paid = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    balance = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    payment_status = db.Column(db.String(30), default="Unpaid", nullable=False)
    payment_method = db.Column(db.String(50), default="Cash", nullable=False)
    notes = db.Column(db.Text, nullable=True)

    transaction_date = db.Column(db.Date, default=date.today, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    payments = db.relationship(
        "CommercialPayment",
        backref="transaction",
        cascade="all, delete-orphan",
        lazy=True,
    )


class CommercialPayment(db.Model):
    __tablename__ = "commercial_payments"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("commercial_transactions.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_method = db.Column(db.String(50), default="Cash", nullable=False)
    payment_date = db.Column(db.Date, default=date.today, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    user_full_name = db.Column(db.String(150), nullable=True)
    username = db.Column(db.String(80), nullable=True)
    user_role = db.Column(db.String(30), nullable=True)
    action = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    user = db.relationship("User", lazy=True)

    @property
    def display_name(self):
        if self.user_full_name:
            return self.user_full_name
        if self.user and self.user.full_name:
            return self.user.full_name
        if self.username:
            return self.username
        if self.user and self.user.username:
            return self.user.username
        return "System"

    @property
    def display_username(self):
        if self.username:
            return self.username
        if self.user:
            return self.user.username
        return ""

    @property
    def display_role(self):
        role = self.user_role or (self.user.role if self.user else "system")
        return role.title()
