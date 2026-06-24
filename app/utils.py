import base64
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from flask import session


ONE_PIXEL_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def ensure_project_folders(app):
    folders = [
        app.config["DAILY_REPORT_DIR"],
        app.config["WEEKLY_REPORT_DIR"],
        app.config["MONTHLY_REPORT_DIR"],
        app.config["CUSTOM_REPORT_DIR"],
        app.config["COMMERCIAL_REPORT_DIR"],
        app.config["BACKUP_DIR"],
        Path(app.static_folder) / "css",
        Path(app.static_folder) / "js",
        Path(app.static_folder) / "icons",
    ]

    for folder in folders:
        Path(folder).mkdir(parents=True, exist_ok=True)

    icon_path = Path(app.static_folder) / "icons" / "icon.png"
    if not icon_path.exists():
        icon_path.write_bytes(base64.b64decode(ONE_PIXEL_PNG))


def get_settings():
    from app import db
    from app.models import Setting

    setting = Setting.query.first()
    if not setting:
        setting = Setting()
        db.session.add(setting)
        db.session.commit()
    return setting


def log_action(action, details=""):
    from app import db
    from app.models import AuditLog, User

    try:
        user_id = session.get("user_id")
        user = db.session.get(User, user_id) if user_id else None
        username = user.username if user else session.get("username")
        role = user.role if user else session.get("role")
        full_name = user.full_name if user and user.full_name else username

        log = AuditLog(
            user_id=user_id,
            user_full_name=full_name,
            username=username,
            user_role=role,
            action=action,
            details=details
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()


def generate_transaction_number():
    from app.models import MillingTransaction

    today = date.today()
    prefix = f"TRX-{today.strftime('%Y%m%d')}"
    return _next_daily_transaction_number(MillingTransaction, prefix)


def _next_daily_transaction_number(model, prefix):
    # The sequence must be derived from every number that already shares this
    # prefix (the prefix is keyed to the creation day). Scoping by transaction_date
    # is wrong: the user can pick any transaction_date, so a row created today can
    # carry a different date and be missed here, producing a duplicate number that
    # violates the UNIQUE constraint on transaction_number.
    rows = model.query.with_entities(model.transaction_number).filter(
        model.transaction_number.like(f"{prefix}-%"),
    ).all()

    highest_sequence = 0
    for (transaction_number,) in rows:
        suffix = str(transaction_number or "").rsplit("-", 1)[-1]
        if suffix.isdigit():
            highest_sequence = max(highest_sequence, int(suffix))

    return f"{prefix}-{highest_sequence + 1:04d}"


def generate_local_customer_name(transaction_date=None):
    from app.models import MillingTransaction

    target_date = transaction_date or date.today()
    count_today = MillingTransaction.query.filter(
        MillingTransaction.transaction_date == target_date
    ).count()
    return f"Customer No. {count_today + 1}"


def local_ticket_number(trx):
    """Daily ticket number for a local (milling) transaction.

    Matches the daily Customer No.: if the customer name still reads
    "Customer No. N" we use N directly; otherwise (name was edited) we fall
    back to the transaction's daily sequence position. Both are scoped to the
    transaction_date, so the number resets every day.
    """
    from app.models import MillingTransaction

    match = re.search(r"Customer No\.\s*(\d+)", trx.customer_name or "")
    if match:
        return int(match.group(1))

    return MillingTransaction.query.filter(
        MillingTransaction.transaction_date == trx.transaction_date,
        MillingTransaction.id <= trx.id,
    ).count()


def format_ticket_datetime(value):
    """Format a datetime for the printed ticket, e.g. '2026-06-20 11:34 AM'."""
    value = value or datetime.now()
    return value.strftime("%Y-%m-%d %I:%M %p")


def generate_commercial_transaction_number():
    from app.models import CommercialTransaction

    today = date.today()
    prefix = f"COM-{today.strftime('%Y%m%d')}"
    return _next_daily_transaction_number(CommercialTransaction, prefix)


def parse_date(value, fallback=None):
    if not value:
        return fallback or date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


def get_date_range(filter_name, custom_date=None):
    today = date.today()

    if filter_name == "yesterday":
        day = today - timedelta(days=1)
        return day, day

    if filter_name == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end

    if filter_name == "custom" and custom_date:
        day = parse_date(custom_date, today)
        return day, day

    return today, today


def report_files():
    from flask import current_app

    root = Path(current_app.config["EXPORT_DIR"])
    files = []

    if not root.exists():
        return files

    for path in root.rglob("*.xlsx"):
        files.append({
            "name": path.name,
            "path": str(path),
            "folder": path.parent.name,
            "created": datetime.fromtimestamp(path.stat().st_mtime),
        })

    files.sort(key=lambda x: x["created"], reverse=True)
    return files[:30]
