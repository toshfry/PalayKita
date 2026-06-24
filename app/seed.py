from sqlalchemy import text
from app import db
from app.models import User, Setting
from app.auth import hash_password


def _column_exists(table_name: str, column_name: str) -> bool:
    rows = db.session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def _add_column_if_missing(table_name: str, column_name: str, ddl: str):
    if not _column_exists(table_name, column_name):
        db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
        db.session.commit()


def migrate_existing_database():
    """Small SQLite-safe migration helper for users upgrading older PalayKita ZIPs."""
    _add_column_if_missing("users", "full_name", "VARCHAR(150)")
    _add_column_if_missing("users", "is_active", "BOOLEAN NOT NULL DEFAULT 1")
    _add_column_if_missing("users", "last_login", "DATETIME")
    _add_column_if_missing("users", "updated_at", "DATETIME")
    _add_column_if_missing("settings", "server_port", "INTEGER NOT NULL DEFAULT 5000")
    _add_column_if_missing("settings", "commercial_default_price_per_sack", "NUMERIC(12, 2) NOT NULL DEFAULT 0")
    _add_column_if_missing("settings", "commercial_enabled", "BOOLEAN NOT NULL DEFAULT 1")
    _add_column_if_missing("settings", "commercial_default_payment_status", "VARCHAR(30) NOT NULL DEFAULT 'Unpaid'")
    _add_column_if_missing("settings", "commercial_notes_enabled", "BOOLEAN NOT NULL DEFAULT 1")
    _add_column_if_missing("settings", "commercial_receipt_label", "VARCHAR(120) NOT NULL DEFAULT 'Commercial Transaction'")
    _add_column_if_missing("settings", "ticket_printing_enabled", "BOOLEAN NOT NULL DEFAULT 1")
    _add_column_if_missing("settings", "ticket_show_after_save", "BOOLEAN NOT NULL DEFAULT 1")
    _add_column_if_missing("settings", "ticket_paper_size", "VARCHAR(10) NOT NULL DEFAULT '80mm'")
    _add_column_if_missing("settings", "ticket_mill_name", "VARCHAR(150) NOT NULL DEFAULT 'Arman Rice Mill'")
    _add_column_if_missing("settings", "ticket_footer_message", "VARCHAR(255) NOT NULL DEFAULT 'Please present this ticket when paying.'")
    _add_column_if_missing("commercial_transactions", "payment_method", "VARCHAR(50) NOT NULL DEFAULT 'Cash'")
    _add_column_if_missing("audit_logs", "user_full_name", "VARCHAR(150)")
    _add_column_if_missing("audit_logs", "username", "VARCHAR(80)")
    _add_column_if_missing("audit_logs", "user_role", "VARCHAR(30)")

    db.session.execute(text("UPDATE users SET is_active = 1 WHERE is_active IS NULL"))
    db.session.execute(text("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL"))
    db.session.execute(text("UPDATE settings SET commercial_enabled = 1 WHERE commercial_enabled IS NULL"))
    db.session.execute(text("UPDATE settings SET commercial_notes_enabled = 1 WHERE commercial_notes_enabled IS NULL"))
    db.session.execute(text("UPDATE settings SET commercial_default_payment_status = 'Unpaid' WHERE commercial_default_payment_status IS NULL OR commercial_default_payment_status = ''"))
    db.session.execute(text("UPDATE settings SET commercial_receipt_label = 'Commercial Transaction' WHERE commercial_receipt_label IS NULL OR commercial_receipt_label = ''"))
    db.session.execute(text("UPDATE commercial_transactions SET payment_method = 'Cash' WHERE payment_method IS NULL OR payment_method = ''"))
    db.session.execute(text("""
        UPDATE audit_logs
        SET username = COALESCE(NULLIF(username, ''), (
                SELECT users.username FROM users WHERE users.id = audit_logs.user_id
            )),
            user_full_name = COALESCE(NULLIF(user_full_name, ''), (
                SELECT COALESCE(NULLIF(users.full_name, ''), users.username)
                FROM users
                WHERE users.id = audit_logs.user_id
            )),
            user_role = COALESCE(NULLIF(user_role, ''), (
                SELECT users.role FROM users WHERE users.id = audit_logs.user_id
            ))
        WHERE user_id IS NOT NULL
    """))
    db.session.commit()


def seed_defaults():
    migrate_existing_database()

    if not User.query.filter_by(username="admin").first():
        admin = User(
            username="admin",
            full_name="System Administrator",
            password_hash=hash_password("admin123"),
            role="admin",
            is_active=True,
        )
        db.session.add(admin)

    if not Setting.query.first():
        settings = Setting(
            business_name="PalayKita Rice Mill",
            milling_rate_per_kg=3.00,
            chaff_rate_per_kg=1.00,
            currency_symbol="₱",
            receipt_footer="Thank you for trusting our rice mill.",
            auto_generate_daily_report=False,
            daily_report_time="18:00",
            server_port=5000,
            commercial_default_price_per_sack=0,
            commercial_enabled=True,
            commercial_default_payment_status="Unpaid",
            commercial_notes_enabled=True,
            commercial_receipt_label="Commercial Transaction",
            ticket_printing_enabled=True,
            ticket_show_after_save=True,
            ticket_paper_size="80mm",
            ticket_mill_name="Arman Rice Mill",
            ticket_footer_message="Please present this ticket when paying.",
        )
        db.session.add(settings)

    db.session.commit()
