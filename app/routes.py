from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
import re

from sqlalchemy import or_
from openpyxl import Workbook

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_file,
    abort,
    current_app,
)

from app import APP_VERSION, db
from app.models import User, MillingTransaction, Payment, CommercialCustomer, CommercialTransaction, CommercialPayment, AuditLog
from app.auth import verify_password, hash_password, login_required, admin_required, current_user
from app.calculations import compute_transaction, compute_commercial_transaction, money, format_money
from app.utils import (
    get_settings,
    generate_transaction_number,
    generate_local_customer_name,
    generate_commercial_transaction_number,
    parse_date,
    get_date_range,
    log_action,
    report_files,
    local_ticket_number,
    format_ticket_datetime,
)
from app.reports import (
    generate_excel_report,
    generate_commercial_customer_report,
    daily_range,
    weekly_range,
    monthly_range,
)
from app.desktop_export import export_report_file
from app.server_control import shared_server_manager, get_server_status, DESKTOP_PORT, normalize_port
from app.licensing import activate_from_key, get_computer_id, is_activated, license_status


main_bp = Blueprint("main", __name__)


def is_desktop_request() -> bool:
    """True only for the private desktop-window server at 127.0.0.1:5050."""
    host = (request.host or "").lower()
    hostname = request.host.split(":")[0].lower() if request.host else ""

    try:
        port = int(request.host.split(":")[-1]) if ":" in request.host else 80
    except ValueError:
        port = 80

    return port == DESKTOP_PORT and hostname in {"127.0.0.1", "localhost"}


@main_bp.app_context_processor
def inject_globals():
    settings = get_settings()
    return {
        "settings": settings,
        "money": lambda value: format_money(value, settings.currency_symbol),
        "current_user": current_user(),
        "today_date": date.today(),
        "desktop_mode": is_desktop_request(),
        "app_version": APP_VERSION,
    }


@main_bp.app_errorhandler(404)
def handle_not_found(error):
    return render_template(
        "error.html",
        code=404,
        title="Page not found",
        message="The page you were looking for doesn't exist.",
    ), 404


@main_bp.app_errorhandler(500)
def handle_server_error(error):
    db.session.rollback()
    return render_template(
        "error.html",
        code=500,
        title="Something went wrong",
        message="An unexpected error occurred. Please try again, or go back to the dashboard.",
    ), 500


@main_bp.before_app_request
def require_activation():
    """
    First-time activation guard.

    If PalayKita is not activated or the license expired, block normal pages
    and show the activation page before login.
    """
    endpoint = request.endpoint or ""
    path = request.path or ""

    allowed_endpoints = {
        "static",
        "main.activation",
    }

    if endpoint in allowed_endpoints:
        return

    if path.startswith("/static/"):
        return

    if is_activated():
        return

    # Do not keep logged-in sessions when license is invalid/expired.
    session.clear()
    return redirect(url_for("main.activation"))


@main_bp.route("/activation", methods=["GET", "POST"])
def activation():
    status = license_status()

    if request.method == "POST":
        activation_key = request.form.get("activation_key", "").strip()
        valid, message, payload = activate_from_key(activation_key)

        if valid:
            flash("PalayKita activated successfully. You may now login.", "success")
            return redirect(url_for("main.login"))

        flash(message, "danger")
        status = license_status()

    return render_template(
        "activation.html",
        status=status,
        computer_id=get_computer_id(),
    )


@main_bp.before_app_request
def auto_daily_report_check():
    if not session.get("user_id"):
        return

    settings = get_settings()
    if not settings.auto_generate_daily_report:
        return

    now_time = datetime.now().strftime("%H:%M")
    if now_time < settings.daily_report_time:
        return

    today = date.today()
    filename = f"PalayKita_Daily_Report_{today.strftime('%Y-%m-%d')}.xlsx"
    path = Path(current_app.config["DAILY_REPORT_DIR"]) / filename

    if not path.exists():
        try:
            generate_excel_report("daily", today, today)
        except Exception:
            pass


@main_bp.route("/", methods=["GET"])
def index():
    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("main.login"))


@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and verify_password(user.password_hash, password):
            if not user.is_active:
                flash("This account is disabled. Please contact an admin.", "danger")
                return render_template("login.html")

            user.last_login = datetime.now()
            db.session.commit()

            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role
            log_action("Login", f"{user.username} logged in.")
            flash("Welcome to PalayKita.", "success")
            return redirect(url_for("main.dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@main_bp.route("/logout")
@login_required
def logout():
    log_action("Logout", f"{session.get('username')} logged out.")
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.login"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    today = date.today()
    recent_filter = request.args.get("recent_filter", "All")
    recent_filters = ["All", "Local", "Commercial", "Paid", "Partial", "Unpaid"]
    if recent_filter not in recent_filters:
        recent_filter = "All"

    transactions = MillingTransaction.query.filter(
        MillingTransaction.transaction_date == today
    ).all()
    commercial_transactions_today = CommercialTransaction.query.filter(
        CommercialTransaction.transaction_date == today
    ).all()

    local_unpaid = MillingTransaction.query.filter(
        MillingTransaction.payment_status.in_(["Unpaid", "Partial"])
    ).count()
    commercial_unpaid_transactions = CommercialTransaction.query.filter(
        CommercialTransaction.payment_status.in_(["Unpaid", "Partial"])
    ).all()
    commercial_unpaid_customers = len({
        transaction.customer_id for transaction in commercial_unpaid_transactions
    })
    commercial_unpaid_count = len(commercial_unpaid_transactions)

    local_income_today = sum(money(t.net_amount) for t in transactions)
    commercial_income_today = sum(money(t.total_amount) for t in commercial_transactions_today)
    local_paid_today = sum(money(t.amount_paid) for t in transactions)
    commercial_paid_today = sum(money(t.amount_paid) for t in commercial_transactions_today)
    local_unpaid_today = sum(money(t.balance) for t in transactions)
    commercial_unpaid_today = sum(money(t.balance) for t in commercial_transactions_today)
    local_kilos_today = sum(money(t.kilos_milled) for t in transactions)
    commercial_sacks_today = sum(money(t.number_of_sacks) for t in commercial_transactions_today)

    total_sales_today = local_income_today + commercial_income_today
    cash_collected_today = local_paid_today + commercial_paid_today

    local_recent_query = MillingTransaction.query
    commercial_recent_query = CommercialTransaction.query

    if recent_filter in ["Paid", "Partial", "Unpaid"]:
        local_recent_query = local_recent_query.filter(MillingTransaction.payment_status == recent_filter)
        commercial_recent_query = commercial_recent_query.filter(CommercialTransaction.payment_status == recent_filter)

    recent_transactions = []
    if recent_filter in ["All", "Local", "Paid", "Partial", "Unpaid"]:
        for trx in local_recent_query.order_by(
            MillingTransaction.transaction_date.desc(),
            MillingTransaction.created_at.desc(),
        ).limit(12).all():
            recent_transactions.append({
                "type": "Local",
                "transaction_number": trx.transaction_number,
                "transaction_date": trx.transaction_date,
                "created_at": trx.created_at,
                "customer": trx.customer_name or "Walk-in / Not specified",
                "quantity": f"{money(trx.kilos_milled):,.2f} kg",
                "income": trx.net_amount,
                "paid": trx.amount_paid,
                "balance": trx.balance,
                "payment_status": trx.payment_status,
                "url": url_for("main.view_transaction", transaction_id=trx.id),
            })

    if recent_filter in ["All", "Commercial", "Paid", "Partial", "Unpaid"]:
        for trx in commercial_recent_query.order_by(
            CommercialTransaction.transaction_date.desc(),
            CommercialTransaction.created_at.desc(),
        ).limit(12).all():
            recent_transactions.append({
                "type": "Commercial",
                "transaction_number": trx.transaction_number,
                "transaction_date": trx.transaction_date,
                "created_at": trx.created_at,
                "customer": trx.customer.name if trx.customer else "Registered customer",
                "quantity": f"{money(trx.number_of_sacks):,.2f} sacks",
                "income": trx.total_amount,
                "paid": trx.amount_paid,
                "balance": trx.balance,
                "payment_status": trx.payment_status,
                "url": url_for("main.commercial_customer_detail", customer_id=trx.customer_id),
            })

    recent_transactions.sort(
        key=lambda item: (
            item["transaction_date"] or date.min,
            item["created_at"] or datetime.min,
            item["transaction_number"],
        ),
        reverse=True,
    )
    recent_transactions = recent_transactions[:12]

    summary = {
        "net_income_today": total_sales_today,
        "total_sales_today": total_sales_today,
        "cash_collected_today": cash_collected_today,
        "local_net_today": local_income_today,
        "commercial_sales_today": commercial_income_today,
        "commercial_sacks_today": commercial_sacks_today,
        "gross_today": sum(money(t.gross_fee) for t in transactions),
        "chaff_today": sum(money(t.chaff_deduction) for t in transactions),
        "kilos_today": local_kilos_today,
        "transactions_today": len(transactions) + len(commercial_transactions_today),
        "local_transactions_today": len(transactions),
        "commercial_transactions_today": len(commercial_transactions_today),
        "unpaid_today": local_unpaid_today + commercial_unpaid_today,
        "total_unpaid": local_unpaid + commercial_unpaid_count,
        "metrics": {
            "transactions": {
                "local": len(transactions),
                "commercial": len(commercial_transactions_today),
                "total": len(transactions) + len(commercial_transactions_today),
            },
            "income": {
                "local": local_income_today,
                "commercial": commercial_income_today,
                "total": total_sales_today,
            },
            "paid": {
                "local": local_paid_today,
                "commercial": commercial_paid_today,
                "total": cash_collected_today,
            },
            "unpaid": {
                "local": local_unpaid_today,
                "commercial": commercial_unpaid_today,
                "total": local_unpaid_today + commercial_unpaid_today,
            },
            "unpaid_accounts": {
                "local": local_unpaid,
                "commercial": commercial_unpaid_count,
                "total": local_unpaid + commercial_unpaid_count,
            },
        },
        "local_summary": {
            "transactions": len(transactions),
            "kilos": local_kilos_today,
            "income": local_income_today,
            "paid": local_paid_today,
            "unpaid": local_unpaid_today,
        },
        "commercial_summary": {
            "transactions": len(commercial_transactions_today),
            "sacks": commercial_sacks_today,
            "income": commercial_income_today,
            "paid": commercial_paid_today,
            "unpaid": commercial_unpaid_today,
            "unpaid_customers": commercial_unpaid_customers,
        },
    }

    return render_template(
        "dashboard.html",
        summary=summary,
        recent_filter=recent_filter,
        recent_filters=recent_filters,
        recent_transactions=recent_transactions,
    )


@main_bp.route("/transactions/new", methods=["GET", "POST"])
@login_required
def new_transaction():
    settings = get_settings()
    transaction_type = request.args.get("type", "local")
    if transaction_type not in ["local", "commercial"]:
        transaction_type = "local"

    commercial_customers = CommercialCustomer.query.filter_by(status="Active").order_by(
        CommercialCustomer.name.asc()
    ).all()
    selected_commercial_customer_id = request.args.get("customer_id", "")
    default_customer_name = generate_local_customer_name() if transaction_type == "local" else ""

    if request.method == "POST":
        transaction_type = request.form.get("transaction_type", "local")

        if transaction_type == "commercial":
            if not settings.commercial_enabled:
                flash("Commercial transactions are disabled in Settings.", "warning")
                return redirect(url_for("main.new_transaction"))

            raw_customer_id = request.form.get("commercial_customer_id", "").strip()
            customer = None
            if raw_customer_id.isdigit():
                customer = CommercialCustomer.query.filter_by(
                    id=int(raw_customer_id),
                    status="Active",
                ).first()

            if not customer:
                flash("Select a registered active commercial customer before saving.", "danger")
                return redirect(url_for("main.new_transaction", type="commercial"))

            computed = compute_commercial_transaction(
                number_of_sacks=request.form.get("number_of_sacks"),
                price_per_sack=request.form.get("price_per_sack"),
                amount_paid=request.form.get("amount_paid"),
            )

            if computed["number_of_sacks"] <= 0:
                flash("Number of sacks must be greater than zero.", "danger")
                return redirect(url_for("main.new_transaction", type="commercial", customer_id=customer.id))

            if computed["price_per_sack"] <= 0:
                flash("Price per sack must be greater than zero.", "danger")
                return redirect(url_for("main.new_transaction", type="commercial", customer_id=customer.id))

            trx = CommercialTransaction(
                transaction_number=generate_commercial_transaction_number(),
                customer_id=customer.id,
                number_of_sacks=computed["number_of_sacks"],
                price_per_sack=computed["price_per_sack"],
                total_amount=computed["total_amount"],
                amount_paid=computed["amount_paid"],
                balance=computed["balance"],
                payment_status=computed["payment_status"],
                payment_method=request.form.get("payment_method", "Cash"),
                notes=request.form.get("notes", "").strip() or None,
                transaction_date=parse_date(request.form.get("transaction_date"), date.today()),
                created_by=session.get("user_id"),
            )

            db.session.add(trx)
            db.session.commit()

            log_action("Create Commercial Transaction", f"Created {trx.transaction_number}")
            flash("Commercial transaction saved successfully.", "success")
            return redirect(url_for("main.new_transaction", type="commercial"))

        has_chaff = request.form.get("has_chaff_deduction") == "yes"

        computed = compute_transaction(
            kilos_milled=request.form.get("kilos_milled"),
            milling_rate_per_kg=request.form.get("milling_rate_per_kg"),
            has_chaff_deduction=has_chaff,
            chaff_kilos=request.form.get("chaff_kilos"),
            chaff_rate_per_kg=request.form.get("chaff_rate_per_kg"),
            amount_paid=request.form.get("amount_paid"),
        )

        if computed["kilos_milled"] <= 0:
            flash("Kilos milled must be greater than zero.", "danger")
            return redirect(url_for("main.new_transaction", type="local"))
        if computed["amount_paid"] < 0:
            flash("Amount paid cannot be negative.", "danger")
            return redirect(url_for("main.new_transaction", type="local"))

        transaction_date = parse_date(request.form.get("transaction_date"), date.today())
        customer_name = request.form.get("customer_name", "").strip()
        if not customer_name:
            customer_name = generate_local_customer_name(transaction_date)

        trx = MillingTransaction(
            transaction_number=generate_transaction_number(),
            customer_name=customer_name,
            contact_number=request.form.get("contact_number", "").strip() or None,
            kilos_milled=computed["kilos_milled"],
            milling_rate_per_kg=computed["milling_rate_per_kg"],
            gross_fee=computed["gross_fee"],
            has_chaff_deduction=computed["has_chaff_deduction"],
            chaff_kilos=computed["chaff_kilos"],
            chaff_rate_per_kg=computed["chaff_rate_per_kg"],
            chaff_deduction=computed["chaff_deduction"],
            net_amount=computed["net_amount"],
            amount_paid=computed["amount_paid"],
            balance=computed["balance"],
            payment_status=computed["payment_status"],
            payment_method=request.form.get("payment_method", "Cash"),
            notes=request.form.get("notes", "").strip() or None,
            transaction_date=transaction_date,
            created_by=session.get("user_id"),
        )

        db.session.add(trx)
        db.session.commit()

        log_action("Create Transaction", f"Created {trx.transaction_number}")

        # Remember the last saved local transaction so the New Transaction page can
        # offer a Print Ticket button and Settings can reprint the last ticket.
        session["last_local_ticket_id"] = trx.id

        if trx.balance > 0 and not trx.customer_name:
            flash(
                "Transaction saved. Warning: this transaction has an unpaid balance but no customer name.",
                "warning"
            )
        else:
            flash("Transaction saved successfully.", "success")

        if settings.ticket_printing_enabled and settings.ticket_show_after_save:
            return redirect(url_for("main.new_transaction", type="local", saved_ticket=trx.id))
        return redirect(url_for("main.new_transaction", type="local"))

    # A just-saved local transaction (carried via ?saved_ticket=<id>) drives the
    # Print Ticket button above the form. Commercial saves never set this arg.
    saved_ticket = None
    saved_ticket_number = None
    saved_ticket_id = request.args.get("saved_ticket", "")
    if saved_ticket_id.isdigit():
        saved_ticket = db.session.get(MillingTransaction, int(saved_ticket_id))
        if saved_ticket:
            saved_ticket_number = local_ticket_number(saved_ticket)

    return render_template(
        "transaction_form.html",
        mode="new",
        transaction=None,
        transaction_type=transaction_type,
        commercial_customers=commercial_customers,
        selected_commercial_customer_id=selected_commercial_customer_id,
        default_customer_name=default_customer_name,
        commercial_enabled=settings.commercial_enabled,
        default_commercial_price=settings.commercial_default_price_per_sack,
        default_commercial_payment_status=settings.commercial_default_payment_status,
        commercial_notes_enabled=settings.commercial_notes_enabled,
        default_milling_rate=settings.milling_rate_per_kg,
        default_chaff_rate=settings.chaff_rate_per_kg,
        saved_ticket=saved_ticket,
        saved_ticket_number=saved_ticket_number,
        today=date.today()
    )


def _local_ticket_context(trx, settings):
    """Build the print context for a saved local transaction.

    Shows ONLY the customer-facing fields. Never includes amount paid, balance,
    status, payment method, notes, or chaff details.
    """
    return {
        "mill_name": settings.ticket_mill_name,
        "footer_message": settings.ticket_footer_message,
        "ticket_no": local_ticket_number(trx),
        "transaction_number": trx.transaction_number,
        "date_time": format_ticket_datetime(trx.created_at),
        "customer_name": trx.customer_name or "—",
        "kilos": f"{money(trx.kilos_milled):.2f}",
        "price_per_kilo": f"{money(trx.milling_rate_per_kg):.2f}",
        "total_amount": f"{money(trx.gross_fee):.2f}",
        "is_test": False,
    }


@main_bp.route("/transactions/<int:transaction_id>/ticket")
@login_required
def local_ticket(transaction_id):
    settings = get_settings()

    if not settings.ticket_printing_enabled:
        flash("Local ticket printing is turned off in Settings.", "warning")
        return redirect(url_for("main.new_transaction", type="local"))

    trx = db.session.get(MillingTransaction, transaction_id)
    if not trx:
        flash("That transaction could not be found for ticket printing.", "danger")
        return redirect(url_for("main.new_transaction", type="local"))

    is_reprint = request.args.get("reprint") == "1"
    context = _local_ticket_context(trx, settings)

    log_action(
        "Reprint Local Ticket" if is_reprint else "Print Local Ticket",
        f"{trx.transaction_number} (Ticket #{context['ticket_no']})",
    )

    return render_template("ticket.html", **context)


@main_bp.route("/settings/ticket/test")
@login_required
@admin_required
def test_local_ticket():
    settings = get_settings()
    context = {
        "mill_name": settings.ticket_mill_name,
        "footer_message": settings.ticket_footer_message,
        "ticket_no": 30,
        "transaction_number": "TRX-20260621-0001",
        "date_time": format_ticket_datetime(datetime.now()),
        "customer_name": "Customer No. 30",
        "kilos": "120.00",
        "price_per_kilo": "2.50",
        "total_amount": "300.00",
        "is_test": True,
    }
    log_action("Test Local Ticket", "Printed a sample local ticket from Settings.")
    return render_template("ticket.html", **context)


@main_bp.route("/transactions")
@login_required
def transactions():
    filter_name = request.args.get("filter", "today")
    custom_date = request.args.get("custom_date")
    status = request.args.get("status", "all")
    transaction_type = request.args.get("type", "all")
    if transaction_type not in ["all", "local", "commercial"]:
        transaction_type = "all"

    start, end = get_date_range(filter_name, custom_date)

    rows = []

    if transaction_type in ["all", "local"]:
        local_query = MillingTransaction.query.filter(
            MillingTransaction.transaction_date >= start,
            MillingTransaction.transaction_date <= end
        )

        if status in ["Paid", "Partial", "Unpaid"]:
            local_query = local_query.filter(MillingTransaction.payment_status == status)

        for trx in local_query.all():
            rows.append({
                "type": "Local",
                "payment_type": "local",
                "id": trx.id,
                "transaction_number": trx.transaction_number,
                "transaction_date": trx.transaction_date,
                "created_at": trx.created_at,
                "customer": trx.customer_name or "Walk-in / Not specified",
                "quantity": f"{money(trx.kilos_milled):,.2f} kg",
                "gross": trx.gross_fee,
                "chaff": trx.chaff_deduction,
                "total": trx.net_amount,
                "paid": trx.amount_paid,
                "balance": trx.balance,
                "payment_status": trx.payment_status,
                "payment_method": trx.payment_method or "Cash",
                "view_url": url_for("main.view_transaction", transaction_id=trx.id),
                "edit_url": url_for("main.edit_transaction", transaction_id=trx.id),
                "mark_paid_url": url_for("main.mark_paid", transaction_id=trx.id),
                "delete_url": url_for("main.delete_transaction", transaction_id=trx.id),
            })

    if transaction_type in ["all", "commercial"]:
        commercial_query = CommercialTransaction.query.filter(
            CommercialTransaction.transaction_date >= start,
            CommercialTransaction.transaction_date <= end
        )

        if status in ["Paid", "Partial", "Unpaid"]:
            commercial_query = commercial_query.filter(CommercialTransaction.payment_status == status)

        for trx in commercial_query.all():
            rows.append({
                "type": "Commercial",
                "payment_type": "commercial",
                "id": trx.id,
                "transaction_number": trx.transaction_number,
                "transaction_date": trx.transaction_date,
                "created_at": trx.created_at,
                "customer": trx.customer.name if trx.customer else "Registered customer",
                "quantity": f"{money(trx.number_of_sacks):,.2f} sacks",
                "gross": trx.total_amount,
                "chaff": None,
                "total": trx.total_amount,
                "paid": trx.amount_paid,
                "balance": trx.balance,
                "payment_status": trx.payment_status,
                "payment_method": trx.payment_method or "-",
                "view_url": url_for("main.commercial_customer_detail", customer_id=trx.customer_id),
                "edit_url": url_for(
                    "main.edit_commercial_transaction",
                    transaction_id=trx.id,
                    next=request.full_path,
                ),
                "mark_paid_url": url_for("main.mark_commercial_paid", transaction_id=trx.id),
                "delete_url": None,
            })

    rows.sort(
        key=lambda item: (
            item["transaction_date"] or date.min,
            item["created_at"] or datetime.min,
            item["transaction_number"],
        ),
        reverse=True,
    )

    type_filter_urls = {}
    for type_value in ["all", "local", "commercial"]:
        args = request.args.to_dict(flat=True)
        args["type"] = type_value
        type_filter_urls[type_value] = url_for("main.transactions", **args)

    return render_template(
        "transactions.html",
        transactions=rows,
        filter_name=filter_name,
        custom_date=custom_date,
        status=status,
        transaction_type=transaction_type,
        type_filter_urls=type_filter_urls,
        start=start,
        end=end
    )


@main_bp.route("/transactions/<int:transaction_id>")
@login_required
def view_transaction(transaction_id):
    trx = MillingTransaction.query.get_or_404(transaction_id)
    return render_template(
        "transaction_form.html",
        mode="view",
        transaction=trx,
        default_milling_rate=trx.milling_rate_per_kg,
        default_chaff_rate=trx.chaff_rate_per_kg,
        today=trx.transaction_date
    )


@main_bp.route("/transactions/<int:transaction_id>/edit", methods=["GET", "POST"])
@login_required
def edit_transaction(transaction_id):
    trx = MillingTransaction.query.get_or_404(transaction_id)

    if request.method == "POST":
        has_chaff = request.form.get("has_chaff_deduction") == "yes"

        computed = compute_transaction(
            kilos_milled=request.form.get("kilos_milled"),
            milling_rate_per_kg=request.form.get("milling_rate_per_kg"),
            has_chaff_deduction=has_chaff,
            chaff_kilos=request.form.get("chaff_kilos"),
            chaff_rate_per_kg=request.form.get("chaff_rate_per_kg"),
            amount_paid=request.form.get("amount_paid"),
        )

        if computed["kilos_milled"] <= 0:
            flash("Kilos milled must be greater than zero.", "danger")
            return redirect(url_for("main.edit_transaction", transaction_id=trx.id))
        if computed["amount_paid"] < 0:
            flash("Amount paid cannot be negative.", "danger")
            return redirect(url_for("main.edit_transaction", transaction_id=trx.id))

        before = _local_transaction_snapshot(trx)

        trx.customer_name = request.form.get("customer_name", "").strip() or None
        trx.contact_number = request.form.get("contact_number", "").strip() or None
        trx.kilos_milled = computed["kilos_milled"]
        trx.milling_rate_per_kg = computed["milling_rate_per_kg"]
        trx.gross_fee = computed["gross_fee"]
        trx.has_chaff_deduction = computed["has_chaff_deduction"]
        trx.chaff_kilos = computed["chaff_kilos"]
        trx.chaff_rate_per_kg = computed["chaff_rate_per_kg"]
        trx.chaff_deduction = computed["chaff_deduction"]
        trx.net_amount = computed["net_amount"]
        trx.amount_paid = computed["amount_paid"]
        trx.balance = computed["balance"]
        trx.payment_status = computed["payment_status"]
        trx.payment_method = request.form.get("payment_method", "Cash")
        trx.notes = request.form.get("notes", "").strip() or None
        trx.transaction_date = parse_date(request.form.get("transaction_date"), trx.transaction_date)
        trx.updated_at = datetime.now()

        after = _local_transaction_snapshot(trx)
        db.session.commit()
        log_action("Edit Transaction", _local_transaction_edit_audit_details(trx, before, after))

        flash("Transaction updated successfully.", "success")
        return redirect(url_for("main.transactions"))

    return render_template(
        "transaction_form.html",
        mode="edit",
        transaction=trx,
        default_milling_rate=trx.milling_rate_per_kg,
        default_chaff_rate=trx.chaff_rate_per_kg,
        today=trx.transaction_date
    )


def _local_transaction_audit_details(prefix, trx):
    symbol = get_settings().currency_symbol
    customer = trx.customer_name or "Walk-in / Not specified"
    return (
        f"{prefix} {trx.transaction_number} | "
        f"Customer: {customer} | "
        f"Kilos: {money(trx.kilos_milled):,.2f} kg | "
        f"Total: {format_money(trx.net_amount, symbol)} | "
        f"Paid: {format_money(trx.amount_paid, symbol)} | "
        f"Balance: {format_money(trx.balance, symbol)} | "
        f"Status: {trx.payment_status}"
    )


def _local_transaction_snapshot(trx):
    return {
        "customer_name": trx.customer_name or "",
        "kilos_milled": money(trx.kilos_milled),
        "milling_rate_per_kg": money(trx.milling_rate_per_kg),
        "gross_fee": money(trx.gross_fee),
        "chaff_deduction": money(trx.chaff_deduction),
        "net_amount": money(trx.net_amount),
        "amount_paid": money(trx.amount_paid),
        "balance": money(trx.balance),
        "payment_status": trx.payment_status,
        "payment_method": trx.payment_method or "Cash",
        "notes": trx.notes or "",
    }


def _local_transaction_edit_audit_details(trx, before, after):
    symbol = get_settings().currency_symbol
    customer = trx.customer_name or "Walk-in / Not specified"

    def money_change(label, key):
        if before[key] == after[key]:
            return None
        return f"{label}: {format_money(before[key], symbol)} -> {format_money(after[key], symbol)}"

    def quantity_change(label, key, unit=""):
        if before[key] == after[key]:
            return None
        suffix = f" {unit}" if unit else ""
        return f"{label}: {before[key]:,.2f}{suffix} -> {after[key]:,.2f}{suffix}"

    def text_change(label, key):
        if before[key] == after[key]:
            return None
        old_value = before[key] or "-"
        new_value = after[key] or "-"
        return f"{label}: {old_value} -> {new_value}"

    changes = [
        text_change("Customer", "customer_name"),
        quantity_change("Kilos", "kilos_milled", "kg"),
        money_change("Rate/Kilo", "milling_rate_per_kg"),
        money_change("Gross", "gross_fee"),
        money_change("Chaff Deduction", "chaff_deduction"),
        money_change("Net", "net_amount"),
        money_change("Paid", "amount_paid"),
        money_change("Balance", "balance"),
        text_change("Status", "payment_status"),
        text_change("Method", "payment_method"),
        text_change("Notes", "notes"),
    ]
    changes = [change for change in changes if change]

    if not changes:
        changes = ["No important value changes"]

    return f"Edited {trx.transaction_number} | Customer: {customer} | " + " | ".join(changes)


def _safe_next_url(fallback):
    next_url = request.args.get("next", "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return fallback


def _is_inside_export_dir(resolved_path):
    """True only if resolved_path is genuinely inside the reports export directory.

    Uses real path containment (not a string prefix), so a sibling folder that merely
    shares the prefix (e.g. ``exports/reports_archive``) is correctly rejected.
    """
    export_root = Path(current_app.config["EXPORT_DIR"]).resolve()
    try:
        return resolved_path.is_relative_to(export_root)
    except AttributeError:  # Python < 3.9 fallback
        return resolved_path == export_root or export_root in resolved_path.parents


def _commercial_transaction_snapshot(trx):
    return {
        "number_of_sacks": money(trx.number_of_sacks),
        "price_per_sack": money(trx.price_per_sack),
        "total_amount": money(trx.total_amount),
        "amount_paid": money(trx.amount_paid),
        "balance": money(trx.balance),
        "payment_status": trx.payment_status,
        "payment_method": trx.payment_method or "Cash",
        "notes": trx.notes or "",
    }


def _commercial_transaction_audit_details(trx, before, after):
    symbol = get_settings().currency_symbol
    customer = trx.customer.name if trx.customer else "Registered customer"

    def money_change(label, key):
        if before[key] == after[key]:
            return None
        return f"{label}: {format_money(before[key], symbol)} -> {format_money(after[key], symbol)}"

    def quantity_change(label, key, unit=""):
        if before[key] == after[key]:
            return None
        suffix = f" {unit}" if unit else ""
        return f"{label}: {before[key]:,.2f}{suffix} -> {after[key]:,.2f}{suffix}"

    def text_change(label, key):
        if before[key] == after[key]:
            return None
        old_value = before[key] or "-"
        new_value = after[key] or "-"
        return f"{label}: {old_value} -> {new_value}"

    changes = [
        quantity_change("Sacks", "number_of_sacks", "sacks"),
        money_change("Price/Sack", "price_per_sack"),
        money_change("Total", "total_amount"),
        money_change("Paid", "amount_paid"),
        money_change("Balance", "balance"),
        text_change("Status", "payment_status"),
        text_change("Method", "payment_method"),
        text_change("Notes", "notes"),
    ]
    changes = [change for change in changes if change]

    if not changes:
        changes = ["No important value changes"]

    return f"Edited {trx.transaction_number} | Customer: {customer} | " + " | ".join(changes)


@main_bp.route("/transactions/<int:transaction_id>/delete", methods=["POST"])
@login_required
def delete_transaction(transaction_id):
    trx = MillingTransaction.query.get_or_404(transaction_id)
    details = _local_transaction_audit_details("Deleted", trx)
    db.session.delete(trx)
    db.session.commit()

    log_action("Delete Transaction", details)
    flash("Transaction deleted.", "info")
    return redirect(url_for("main.transactions"))


def _clean_customer_status(value):
    return "Inactive" if value == "Inactive" else "Active"


@main_bp.route("/commercial-customers")
@login_required
def commercial_customers():
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "all")

    query = CommercialCustomer.query
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                CommercialCustomer.name.ilike(pattern),
                CommercialCustomer.contact_number.ilike(pattern),
                CommercialCustomer.address.ilike(pattern),
                CommercialCustomer.notes.ilike(pattern),
            )
        )

    if status_filter in ["Active", "Inactive"]:
        query = query.filter(CommercialCustomer.status == status_filter)

    customers = query.order_by(
        CommercialCustomer.status.asc(),
        CommercialCustomer.name.asc(),
    ).all()

    stats = {
        "total": CommercialCustomer.query.count(),
        "active": CommercialCustomer.query.filter_by(status="Active").count(),
        "inactive": CommercialCustomer.query.filter_by(status="Inactive").count(),
    }

    return render_template(
        "commercial_customers.html",
        customers=customers,
        stats=stats,
        search=search,
        status_filter=status_filter,
    )


@main_bp.route("/commercial-customers/create", methods=["POST"])
@login_required
def create_commercial_customer():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Commercial customer name is required.", "danger")
        return redirect(url_for("main.commercial_customers"))

    customer = CommercialCustomer(
        name=name,
        contact_number=request.form.get("contact_number", "").strip() or None,
        address=request.form.get("address", "").strip() or None,
        notes=request.form.get("notes", "").strip() or None,
        status=_clean_customer_status(request.form.get("status", "Active")),
    )

    db.session.add(customer)
    db.session.commit()
    log_action("Create Commercial Customer", f"Created {customer.name}")
    flash("Commercial customer added.", "success")
    return redirect(url_for("main.commercial_customers"))


@main_bp.route("/commercial-customers/quick-create", methods=["POST"])
@login_required
def quick_create_commercial_customer():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Commercial customer name is required.", "danger")
        return redirect(url_for("main.new_transaction", type="commercial"))

    customer = CommercialCustomer(
        name=name,
        contact_number=request.form.get("contact_number", "").strip() or None,
        address=request.form.get("address", "").strip() or None,
        notes=request.form.get("notes", "").strip() or None,
        status="Active",
    )
    db.session.add(customer)
    db.session.commit()

    log_action("Create Commercial Customer", f"Quick-created {customer.name}")
    flash("Commercial customer added. You can now save the transaction.", "success")
    return redirect(url_for("main.new_transaction", type="commercial", customer_id=customer.id))


@main_bp.route("/commercial-customers/<int:customer_id>")
@login_required
def commercial_customer_detail(customer_id):
    customer = CommercialCustomer.query.get_or_404(customer_id)
    transactions = CommercialTransaction.query.filter_by(customer_id=customer.id).order_by(
        CommercialTransaction.transaction_date.desc(),
        CommercialTransaction.created_at.desc(),
    ).all()

    totals = {
        "sacks": sum(money(t.number_of_sacks) for t in transactions),
        "amount": sum(money(t.total_amount) for t in transactions),
        "paid": sum(money(t.amount_paid) for t in transactions),
        "balance": sum(money(t.balance) for t in transactions),
    }

    payments = (
        CommercialPayment.query
        .join(CommercialTransaction, CommercialPayment.transaction_id == CommercialTransaction.id)
        .filter(CommercialTransaction.customer_id == customer.id)
        .order_by(CommercialPayment.payment_date.desc(), CommercialPayment.created_at.desc())
        .all()
    )

    return render_template(
        "commercial_customer_detail.html",
        customer=customer,
        transactions=transactions,
        totals=totals,
        payments=payments,
    )


@main_bp.route("/commercial-transactions/<int:transaction_id>/edit", methods=["GET", "POST"])
@login_required
def edit_commercial_transaction(transaction_id):
    trx = CommercialTransaction.query.get_or_404(transaction_id)
    fallback_url = url_for("main.commercial_customer_detail", customer_id=trx.customer_id)
    back_url = _safe_next_url(fallback_url)

    if request.method == "POST":
        computed = compute_commercial_transaction(
            number_of_sacks=request.form.get("number_of_sacks"),
            price_per_sack=request.form.get("price_per_sack"),
            amount_paid=request.form.get("amount_paid"),
            total_amount=request.form.get("total_amount"),
        )

        if computed["number_of_sacks"] <= 0:
            flash("Number of sacks must be greater than zero.", "danger")
            return redirect(request.url)

        if computed["price_per_sack"] <= 0:
            flash("Price per sack must be greater than zero.", "danger")
            return redirect(request.url)

        if computed["total_amount"] <= 0:
            flash("Total amount must be greater than zero.", "danger")
            return redirect(request.url)

        if computed["amount_paid"] < 0:
            flash("Amount paid cannot be negative.", "danger")
            return redirect(request.url)

        before = _commercial_transaction_snapshot(trx)

        trx.number_of_sacks = computed["number_of_sacks"]
        trx.price_per_sack = computed["price_per_sack"]
        trx.total_amount = computed["total_amount"]
        trx.amount_paid = computed["amount_paid"]
        trx.balance = computed["balance"]
        trx.payment_status = computed["payment_status"]
        trx.payment_method = request.form.get("payment_method", "Cash")
        trx.notes = request.form.get("notes", "").strip() or None
        trx.transaction_date = parse_date(request.form.get("transaction_date"), trx.transaction_date)
        trx.updated_at = datetime.now()

        after = _commercial_transaction_snapshot(trx)
        db.session.commit()

        log_action("Edit Commercial Transaction", _commercial_transaction_audit_details(trx, before, after))
        flash("Commercial transaction updated successfully.", "success")
        return redirect(back_url)

    return render_template(
        "transaction_form.html",
        mode="edit",
        transaction=trx,
        transaction_type="commercial",
        commercial_customers=[],
        selected_commercial_customer_id=str(trx.customer_id),
        commercial_enabled=True,
        default_commercial_price=trx.price_per_sack,
        default_commercial_payment_status=trx.payment_status,
        commercial_notes_enabled=True,
        default_milling_rate=0,
        default_chaff_rate=0,
        today=trx.transaction_date,
        back_url=back_url,
    )


@main_bp.route("/commercial-customers/<int:customer_id>/edit", methods=["POST"])
@login_required
def edit_commercial_customer(customer_id):
    customer = CommercialCustomer.query.get_or_404(customer_id)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Commercial customer name is required.", "danger")
        return redirect(request.referrer or url_for("main.commercial_customers"))

    customer.name = name
    customer.contact_number = request.form.get("contact_number", "").strip() or None
    customer.address = request.form.get("address", "").strip() or None
    customer.notes = request.form.get("notes", "").strip() or None
    customer.updated_at = datetime.now()

    db.session.commit()
    log_action("Edit Commercial Customer", f"Edited {customer.name}")
    flash("Commercial customer updated.", "success")
    return redirect(request.referrer or url_for("main.commercial_customers"))


@main_bp.route("/commercial-customers/<int:customer_id>/delete", methods=["POST"])
@login_required
def delete_commercial_customer(customer_id):
    customer = CommercialCustomer.query.get_or_404(customer_id)
    name = customer.name

    if customer.commercial_transactions:
        flash("Customer has transaction history. Deactivate instead to keep records and reports intact.", "warning")
        return redirect(url_for("main.commercial_customers"))

    db.session.delete(customer)
    db.session.commit()
    log_action("Delete Commercial Customer", f"Deleted {name}")
    flash("Commercial customer permanently deleted.", "info")

    return redirect(url_for("main.commercial_customers"))


@main_bp.route("/commercial-customers/<int:customer_id>/deactivate", methods=["POST"])
@login_required
def deactivate_commercial_customer(customer_id):
    customer = CommercialCustomer.query.get_or_404(customer_id)
    name = customer.name

    if customer.status == "Inactive":
        flash("Commercial customer is already inactive.", "info")
        return redirect(url_for("main.commercial_customers"))

    customer.status = "Inactive"
    customer.updated_at = datetime.now()
    db.session.commit()

    log_action("Deactivate Commercial Customer", f"Deactivated {name}")
    flash("Commercial customer deactivated. Existing transaction history is still available.", "success")
    return redirect(url_for("main.commercial_customers"))


@main_bp.route("/commercial-customers/<int:customer_id>/reactivate", methods=["POST"])
@login_required
def reactivate_commercial_customer(customer_id):
    customer = CommercialCustomer.query.get_or_404(customer_id)
    name = customer.name

    if customer.status == "Active":
        flash("Commercial customer is already active.", "info")
        return redirect(url_for("main.commercial_customers"))

    customer.status = "Active"
    customer.updated_at = datetime.now()
    db.session.commit()

    log_action("Reactivate Commercial Customer", f"Reactivated {name}")
    flash("Commercial customer reactivated.", "success")
    return redirect(url_for("main.commercial_customers"))


@main_bp.route("/unpaid")
@login_required
def unpaid():
    rows = MillingTransaction.query.filter(
        MillingTransaction.payment_status.in_(["Unpaid", "Partial"])
    ).order_by(
        MillingTransaction.transaction_date.desc(),
        MillingTransaction.created_at.desc()
    ).all()
    commercial_rows = CommercialTransaction.query.filter(
        CommercialTransaction.payment_status.in_(["Unpaid", "Partial"])
    ).order_by(
        CommercialTransaction.transaction_date.desc(),
        CommercialTransaction.created_at.desc()
    ).all()

    return render_template("unpaid.html", transactions=rows, commercial_transactions=commercial_rows)


@main_bp.route("/transactions/<int:transaction_id>/payment", methods=["POST"])
@login_required
def record_payment(transaction_id):
    trx = MillingTransaction.query.get_or_404(transaction_id)

    amount = money(request.form.get("payment_amount"))
    if amount <= 0:
        flash("Payment amount must be greater than zero.", "danger")
        return redirect(request.referrer or url_for("main.unpaid"))

    outstanding = money(trx.net_amount) - money(trx.amount_paid)
    if outstanding <= 0:
        flash("This transaction is already fully paid.", "info")
        return redirect(request.referrer or url_for("main.unpaid"))
    if amount > outstanding:
        amount = outstanding
        flash("Payment was capped to the remaining balance.", "info")

    payment = Payment(
        transaction_id=trx.id,
        amount=amount,
        payment_method=request.form.get("payment_method", "Cash"),
        payment_date=parse_date(request.form.get("payment_date"), date.today()),
        notes=request.form.get("payment_notes", "").strip() or None,
        created_by=session.get("user_id")
    )

    trx.amount_paid = money(trx.amount_paid) + amount
    new_balance = money(trx.net_amount) - money(trx.amount_paid)

    if new_balance <= 0:
        trx.balance = money(0)
        trx.payment_status = "Paid"
    elif trx.amount_paid <= 0:
        trx.balance = new_balance
        trx.payment_status = "Unpaid"
    else:
        trx.balance = new_balance
        trx.payment_status = "Partial"

    trx.updated_at = datetime.now()

    db.session.add(payment)
    db.session.commit()

    log_action("Record Payment", f"Added payment to {trx.transaction_number}")
    flash("Payment recorded successfully.", "success")
    return redirect(request.referrer or url_for("main.unpaid"))


@main_bp.route("/transactions/<int:transaction_id>/mark-paid", methods=["POST"])
@login_required
def mark_paid(transaction_id):
    trx = MillingTransaction.query.get_or_404(transaction_id)

    if trx.balance <= 0:
        flash("Transaction is already paid.", "info")
        return redirect(request.referrer or url_for("main.unpaid"))

    amount = money(trx.balance)
    payment = Payment(
        transaction_id=trx.id,
        amount=amount,
        payment_method=request.form.get("payment_method", "Cash"),
        payment_date=date.today(),
        notes="Marked as paid",
        created_by=session.get("user_id")
    )

    trx.amount_paid = money(trx.net_amount)
    trx.balance = money(0)
    trx.payment_status = "Paid"
    trx.updated_at = datetime.now()

    db.session.add(payment)
    db.session.commit()

    log_action("Mark Paid", f"Marked {trx.transaction_number} as paid")
    flash("Transaction marked as paid.", "success")
    return redirect(request.referrer or url_for("main.unpaid"))


def _commercial_status_from_paid(total_amount, amount_paid):
    balance = money(total_amount) - money(amount_paid)
    if balance <= 0:
        return money(0), "Paid"
    if money(amount_paid) <= 0:
        return money(balance), "Unpaid"
    return money(balance), "Partial"


@main_bp.route("/commercial-transactions/<int:transaction_id>/payment", methods=["POST"])
@login_required
def record_commercial_payment(transaction_id):
    trx = CommercialTransaction.query.get_or_404(transaction_id)

    amount = money(request.form.get("payment_amount"))
    if amount <= 0:
        flash("Payment amount must be greater than zero.", "danger")
        return redirect(request.referrer or url_for("main.commercial_customer_detail", customer_id=trx.customer_id))

    outstanding = money(trx.total_amount) - money(trx.amount_paid)
    if outstanding <= 0:
        flash("This commercial transaction is already fully paid.", "info")
        return redirect(request.referrer or url_for("main.commercial_customer_detail", customer_id=trx.customer_id))
    if amount > outstanding:
        amount = outstanding
        flash("Payment was capped to the remaining balance.", "info")

    trx.amount_paid = money(trx.amount_paid) + amount
    trx.balance, trx.payment_status = _commercial_status_from_paid(trx.total_amount, trx.amount_paid)
    payment_method = request.form.get("payment_method", "").strip()
    if payment_method:
        trx.payment_method = payment_method
    trx.updated_at = datetime.now()

    payment_date = parse_date(request.form.get("payment_date"), date.today())
    payment_note = request.form.get("payment_notes", "").strip()

    db.session.add(CommercialPayment(
        transaction_id=trx.id,
        amount=amount,
        payment_method=request.form.get("payment_method", "").strip() or "Cash",
        payment_date=payment_date,
        notes=payment_note or None,
        created_by=session.get("user_id"),
    ))

    db.session.commit()

    log_action("Record Commercial Payment", f"Added payment to {trx.transaction_number}")
    flash("Commercial payment recorded successfully.", "success")
    return redirect(request.referrer or url_for("main.commercial_customer_detail", customer_id=trx.customer_id))


@main_bp.route("/commercial-transactions/<int:transaction_id>/mark-paid", methods=["POST"])
@login_required
def mark_commercial_paid(transaction_id):
    trx = CommercialTransaction.query.get_or_404(transaction_id)

    if trx.balance <= 0:
        flash("Commercial transaction is already paid.", "info")
        return redirect(request.referrer or url_for("main.commercial_customer_detail", customer_id=trx.customer_id))

    paid_now = money(trx.total_amount) - money(trx.amount_paid)
    trx.amount_paid = money(trx.total_amount)
    trx.balance = money(0)
    trx.payment_status = "Paid"
    trx.updated_at = datetime.now()

    db.session.add(CommercialPayment(
        transaction_id=trx.id,
        amount=paid_now,
        payment_method=trx.payment_method or "Cash",
        payment_date=date.today(),
        notes="Marked as paid",
        created_by=session.get("user_id"),
    ))

    db.session.commit()

    log_action("Mark Commercial Paid", f"Marked {trx.transaction_number} as paid")
    flash("Commercial transaction marked as paid.", "success")
    return redirect(request.referrer or url_for("main.commercial_customer_detail", customer_id=trx.customer_id))


def _parse_audit_datetime(value, end_of_day=False):
    if not value:
        return None
    try:
        parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
    boundary = datetime.max.time() if end_of_day else datetime.min.time()
    return datetime.combine(parsed_date, boundary)


def _audit_filters_from_args(args):
    today_value = date.today().strftime("%Y-%m-%d")
    has_audit_date_filter = "audit_start" in args or "audit_end" in args

    return {
        "search": args.get("audit_search", "").strip(),
        "action": args.get("audit_action", "all"),
        "user": args.get("audit_user", "all"),
        "start": args.get("audit_start", "") if has_audit_date_filter else today_value,
        "end": args.get("audit_end", "") if has_audit_date_filter else today_value,
    }


def _audit_log_query_from_args(args):
    query = AuditLog.query
    filters = _audit_filters_from_args(args)
    search = filters["search"]
    action_filter = filters["action"]
    user_filter = filters["user"]
    start_at = _parse_audit_datetime(filters["start"])
    end_at = _parse_audit_datetime(filters["end"], end_of_day=True)

    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(
            AuditLog.action.ilike(pattern),
            AuditLog.details.ilike(pattern),
            AuditLog.user_full_name.ilike(pattern),
            AuditLog.username.ilike(pattern),
        ))

    if action_filter and action_filter != "all":
        query = query.filter(AuditLog.action == action_filter)

    if user_filter and user_filter != "all":
        query = query.filter(AuditLog.username == user_filter)

    if start_at:
        query = query.filter(AuditLog.created_at >= start_at)

    if end_at:
        query = query.filter(AuditLog.created_at <= end_at)

    return query


def _audit_user_options():
    rows = db.session.query(
        AuditLog.username,
        AuditLog.user_full_name,
    ).filter(
        AuditLog.username.isnot(None),
        AuditLog.username != "",
    ).distinct().order_by(
        AuditLog.user_full_name.asc(),
        AuditLog.username.asc(),
    ).all()

    users = []
    seen = set()
    for username, full_name in rows:
        if username in seen:
            continue
        seen.add(username)
        users.append({
            "username": username,
            "name": full_name or username,
        })
    return users


def _audit_log_workbook(logs):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Audit Log"
    headers = ["Date & Time", "Full Name", "Username", "Role", "Action", "Details"]
    sheet.append(headers)

    for log in logs:
        sheet.append([
            log.created_at.strftime("%Y-%m-%d %I:%M %p") if log.created_at else "",
            log.display_name,
            log.display_username,
            log.display_role,
            log.action,
            log.details or "",
        ])

    widths = [22, 26, 18, 14, 26, 70]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width

    return workbook


def _save_audit_log_report(logs):
    workbook = _audit_log_workbook(logs)
    generated_time = datetime.now().strftime("%H-%M-%S")
    filename = f"PalayKita_Audit_Log_{date.today().strftime('%Y-%m-%d')}_{generated_time}.xlsx"
    folder = Path(current_app.config["EXPORT_DIR"]) / "audit"
    folder.mkdir(parents=True, exist_ok=True)
    output_path = folder / filename
    workbook.save(output_path)
    return output_path


@main_bp.route("/settings/audit-log/export")
@login_required
@admin_required
def export_audit_log():
    logs = _audit_log_query_from_args(request.args).order_by(
        AuditLog.created_at.desc(),
        AuditLog.id.desc(),
    ).all()

    if is_desktop_request():
        output_path = _save_audit_log_report(logs)
        log_action("Prepare Audit Log Report", f"Prepared {output_path.name}")
        flash("Audit Log report is ready for export. Click Export to download the Excel file.", "success")
        return redirect(url_for(
            "main.reports_page",
            audit_report_ready="1",
            prepared_report=output_path.name,
        ))

    workbook = _audit_log_workbook(logs)
    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"PalayKita_Audit_Log_{date.today().strftime('%Y%m%d')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@main_bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    settings_row = get_settings()

    if request.method == "POST":
        settings_row.business_name = request.form.get("business_name", "").strip() or "PalayKita Rice Mill"
        settings_row.milling_rate_per_kg = money(request.form.get("milling_rate_per_kg"))
        settings_row.chaff_rate_per_kg = money(request.form.get("chaff_rate_per_kg"))
        settings_row.currency_symbol = request.form.get("currency_symbol", "₱").strip() or "₱"
        settings_row.receipt_footer = request.form.get("receipt_footer", "").strip()
        settings_row.auto_generate_daily_report = request.form.get("auto_generate_daily_report") == "on"
        settings_row.daily_report_time = request.form.get("daily_report_time", "18:00")
        settings_row.commercial_default_price_per_sack = money(request.form.get("commercial_default_price_per_sack"))
        settings_row.commercial_enabled = request.form.get("commercial_enabled") == "on"
        commercial_status = request.form.get("commercial_default_payment_status", "Unpaid")
        settings_row.commercial_default_payment_status = commercial_status if commercial_status in ["Paid", "Partial", "Unpaid"] else "Unpaid"
        settings_row.commercial_notes_enabled = request.form.get("commercial_notes_enabled") == "on"
        settings_row.commercial_receipt_label = request.form.get("commercial_receipt_label", "").strip() or "Commercial Transaction"

        settings_row.ticket_printing_enabled = request.form.get("ticket_printing_enabled") == "on"
        settings_row.ticket_show_after_save = request.form.get("ticket_show_after_save") == "on"
        settings_row.ticket_paper_size = "80mm"
        settings_row.ticket_mill_name = request.form.get("ticket_mill_name", "").strip() or "Arman Rice Mill"
        settings_row.ticket_footer_message = request.form.get("ticket_footer_message", "").strip() or "Please present this ticket when paying."

        if request.form.get("server_port"):
            try:
                settings_row.server_port = normalize_port(
                    request.form.get("server_port"),
                    getattr(settings_row, "server_port", 5000),
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("main.settings") + "#server-control")

        db.session.commit()
        log_action("Update Settings", "Updated system settings.")

        flash("Settings updated successfully.", "success")
        return redirect(url_for("main.settings"))

    search = request.args.get("user_search", "").strip()
    role_filter = request.args.get("role", "all")
    status_filter = request.args.get("status", "all")

    users_query = User.query

    if search:
        pattern = f"%{search}%"
        users_query = users_query.filter(
            or_(User.username.ilike(pattern), User.full_name.ilike(pattern))
        )

    if role_filter in ["admin", "staff"]:
        users_query = users_query.filter(User.role == role_filter)

    if status_filter == "active":
        users_query = users_query.filter(User.is_active.is_(True))
    elif status_filter == "disabled":
        users_query = users_query.filter(User.is_active.is_(False))

    users = users_query.order_by(User.is_active.desc(), User.role.asc(), User.username.asc()).all()

    user_stats = {
        "total": User.query.count(),
        "active": User.query.filter_by(is_active=True).count(),
        "disabled": User.query.filter_by(is_active=False).count(),
        "admins": User.query.filter_by(role="admin").count(),
        "staff": User.query.filter_by(role="staff").count(),
    }

    audit_logs = _audit_log_query_from_args(request.args).order_by(
        AuditLog.created_at.desc(),
        AuditLog.id.desc(),
    ).limit(200).all()
    audit_actions = [
        row[0] for row in db.session.query(AuditLog.action)
        .filter(AuditLog.action.isnot(None))
        .distinct()
        .order_by(AuditLog.action.asc())
        .all()
    ]
    audit_filters = _audit_filters_from_args(request.args)

    return render_template(
        "settings.html",
        settings_row=settings_row,
        users=users,
        user_stats=user_stats,
        user_search=search,
        role_filter=role_filter,
        status_filter=status_filter,
        server_status=get_server_status(),
        license_info=license_status(),
        audit_logs=audit_logs,
        audit_actions=audit_actions,
        audit_users=_audit_user_options(),
        audit_filters=audit_filters,
        last_local_ticket_id=session.get("last_local_ticket_id"),
    )


def _clean_username(username):
    return (username or "").strip().lower()


def _valid_username(username):
    return bool(re.fullmatch(r"[a-z0-9_.-]{3,40}", username or ""))


def _active_admin_count(exclude_user_id=None):
    query = User.query.filter_by(role="admin", is_active=True)
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.count()


def _display_name(user):
    return user.full_name or user.username


@main_bp.route("/settings/users/create", methods=["POST"])
@login_required
@admin_required
def create_user():
    username = _clean_username(request.form.get("username"))
    full_name = request.form.get("full_name", "").strip() or None
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    role = request.form.get("role", "staff")
    is_active = request.form.get("is_active") == "on"

    if role not in ["admin", "staff"]:
        role = "staff"

    if not _valid_username(username):
        flash("Username must be 3-40 characters and use only letters, numbers, dot, dash, or underscore.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    if not password:
        flash("Password is required.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    if len(password) < 4:
        flash("Password must be at least 4 characters.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    if password != confirm_password:
        flash("Password confirmation does not match.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    if User.query.filter_by(username=username).first():
        flash("Username already exists.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    user = User(
        username=username,
        full_name=full_name,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db.session.add(user)
    db.session.commit()

    log_action("Create User", f"Created user {username} as {role}.")
    flash("User created successfully.", "success")
    return redirect(url_for("main.settings") + "#user-management")


@main_bp.route("/settings/users/<int:user_id>/edit", methods=["POST"])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    username = _clean_username(request.form.get("username"))
    full_name = request.form.get("full_name", "").strip() or None
    role = request.form.get("role", user.role)
    is_active = request.form.get("is_active") == "on"

    if role not in ["admin", "staff"]:
        role = "staff"

    if not _valid_username(username):
        flash("Username must be 3-40 characters and use only letters, numbers, dot, dash, or underscore.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    duplicate = User.query.filter(User.username == username, User.id != user.id).first()
    if duplicate:
        flash("Username already exists.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    if user.id == session.get("user_id") and not is_active:
        flash("You cannot disable the account you are currently using.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    would_remove_active_admin = user.role == "admin" and user.is_active and (role != "admin" or not is_active)
    if would_remove_active_admin and _active_admin_count(exclude_user_id=user.id) <= 0:
        flash("You must keep at least one active admin account.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    user.username = username
    user.full_name = full_name
    user.role = role
    user.is_active = is_active
    user.updated_at = datetime.now()

    db.session.commit()

    if user.id == session.get("user_id"):
        session["username"] = user.username
        session["role"] = user.role

    log_action("Edit User", f"Edited user {user.username}.")
    flash("User details updated successfully.", "success")
    return redirect(url_for("main.settings") + "#user-management")


@main_bp.route("/settings/users/<int:user_id>/password", methods=["POST"])
@login_required
@admin_required
def change_user_password(user_id):
    user = User.query.get_or_404(user_id)
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not password:
        flash("New password is required.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    if len(password) < 4:
        flash("Password must be at least 4 characters.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    if password != confirm_password:
        flash("Password confirmation does not match.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    user.password_hash = hash_password(password)
    user.updated_at = datetime.now()
    db.session.commit()

    log_action("Change User Password", f"Changed password for {user.username}.")
    flash(f"Password updated for {_display_name(user)}.", "success")
    return redirect(url_for("main.settings") + "#user-management")


@main_bp.route("/settings/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == session.get("user_id"):
        flash("You cannot delete the account you are currently using.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    if user.role == "admin" and user.is_active and _active_admin_count(exclude_user_id=user.id) <= 0:
        flash("You must keep at least one active admin account.", "danger")
        return redirect(url_for("main.settings") + "#user-management")

    username = user.username
    db.session.delete(user)
    db.session.commit()

    log_action("Delete User", f"Deleted user {username}.")
    flash("User deleted successfully.", "info")
    return redirect(url_for("main.settings") + "#user-management")



@main_bp.route("/settings/license/change", methods=["POST"])
@login_required
@admin_required
def change_license_key():
    activation_key = request.form.get("activation_key", "").strip()

    if not activation_key:
        flash("Please paste the new license key.", "danger")
        return redirect(url_for("main.settings") + "#license-activation")

    valid, message, payload = activate_from_key(activation_key)

    if not valid:
        flash(message, "danger")
        return redirect(url_for("main.settings") + "#license-activation")

    business = payload.get("business_name", "PalayKita") if payload else "PalayKita"
    license_type = payload.get("license_type", "license") if payload else "license"

    log_action("Change License", f"Updated license for {business} ({license_type}).")
    flash("License key updated successfully.", "success")
    return redirect(url_for("main.settings") + "#license-activation")



@main_bp.route("/settings/server/port", methods=["POST"])
@login_required
@admin_required
def update_server_port():
    settings_row = get_settings()
    try:
        port = normalize_port(request.form.get("server_port"), fallback=None)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.settings") + "#server-control")

    settings_row.server_port = port
    db.session.commit()
    log_action("Update Server Port", f"Updated Wi-Fi server port to {port}")

    if shared_server_manager.is_running():
        flash(f"Server port saved as {port}. Stop and start the server to apply it.", "warning")
    else:
        flash(f"Server port saved as {port}.", "success")
    return redirect(url_for("main.settings") + "#server-control")


@main_bp.route("/settings/server/start", methods=["POST"])
@login_required
@admin_required
def start_wifi_server():
    settings_row = get_settings()
    ok, message = shared_server_manager.start(getattr(settings_row, "server_port", 5000))
    flash(message, "success" if ok else "warning")
    log_action("Start Wi-Fi Server", message)
    return redirect(url_for("main.settings") + "#server-control")


@main_bp.route("/settings/server/stop", methods=["POST"])
@login_required
@admin_required
def stop_wifi_server():
    ok, message = shared_server_manager.stop()
    flash(message, "info" if ok else "warning")
    log_action("Stop Wi-Fi Server", message)
    return redirect(url_for("main.settings") + "#server-control")


@main_bp.route("/reports")
@login_required
def reports_page():
    return render_template(
        "reports.html",
        files=report_files(),
        audit_report_ready=request.args.get("audit_report_ready") == "1",
        prepared_report=request.args.get("prepared_report", ""),
    )


@main_bp.route("/reports/commercial")
@login_required
def commercial_report_page():
    today = date.today()
    start = parse_date(request.args.get("start_date"), today.replace(day=1))
    end = parse_date(request.args.get("end_date"), today)
    if end < start:
        start, end = end, start

    customer_id = request.args.get("customer_id", "all")
    status = request.args.get("status", "all")

    query = CommercialTransaction.query.filter(
        CommercialTransaction.transaction_date >= start,
        CommercialTransaction.transaction_date <= end,
    )

    selected_customer_id = None
    if customer_id.isdigit():
        selected_customer_id = int(customer_id)
        query = query.filter(CommercialTransaction.customer_id == selected_customer_id)

    if status in ["Paid", "Partial", "Unpaid"]:
        query = query.filter(CommercialTransaction.payment_status == status)

    transactions = query.order_by(
        CommercialTransaction.transaction_date.desc(),
        CommercialTransaction.created_at.desc(),
    ).all()

    totals = {
        "sacks": sum(money(t.number_of_sacks) for t in transactions),
        "amount": sum(money(t.total_amount) for t in transactions),
        "paid": sum(money(t.amount_paid) for t in transactions),
        "balance": sum(money(t.balance) for t in transactions),
    }

    customers = CommercialCustomer.query.order_by(CommercialCustomer.name.asc()).all()

    return render_template(
        "commercial_report.html",
        transactions=transactions,
        customers=customers,
        totals=totals,
        start=start,
        end=end,
        selected_customer_id=selected_customer_id,
        status=status,
    )


@main_bp.route("/reports/commercial/export", methods=["POST"])
@login_required
def export_commercial_report():
    today = date.today()
    start = parse_date(request.form.get("start_date"), today.replace(day=1))
    end = parse_date(request.form.get("end_date"), today)
    if end < start:
        flash("End date cannot be earlier than start date.", "danger")
        return redirect(url_for("main.commercial_report_page"))

    customer_id = request.form.get("customer_id", "all")
    selected_customer_id = int(customer_id) if customer_id.isdigit() else None
    status = request.form.get("status", "all")

    path = generate_commercial_customer_report(start, end, selected_customer_id, status)
    log_action("Generate Commercial Report", f"Generated {path.name}")

    if is_desktop_request():
        flash(f"Commercial report generated: {path.name}. Use Export to save it anywhere on this computer.", "success")
    else:
        flash(f"Commercial report generated: {path.name}", "success")

    return redirect(url_for("main.reports_page"))


@main_bp.route("/reports/generate/<report_type>", methods=["POST"])
@login_required
def generate_report(report_type):
    today = date.today()

    if report_type == "today":
        start, end = daily_range(today)
        kind = "daily"
    elif report_type == "yesterday":
        start, end = daily_range(today - timedelta(days=1))
        kind = "daily"
    elif report_type == "weekly":
        start, end = weekly_range(today)
        kind = "weekly"
    elif report_type == "monthly":
        start, end = monthly_range(today)
        kind = "monthly"
    elif report_type == "custom":
        start = parse_date(request.form.get("start_date"), today)
        end = parse_date(request.form.get("end_date"), today)
        if end < start:
            flash("End date cannot be earlier than start date.", "danger")
            return redirect(url_for("main.reports_page"))
        kind = "custom"
    else:
        abort(404)

    status = request.form.get("status", "all")
    if status not in ["all", "Paid", "Partial", "Unpaid"]:
        status = "all"

    path = generate_excel_report(kind, start, end, status)
    log_action("Generate Report", f"Generated {path.name}")

    if is_desktop_request():
        flash(f"Report generated: {path.name}. Use Export to save it anywhere on this computer.", "success")
    else:
        flash(f"Report generated: {path.name}", "success")

    return redirect(url_for("main.reports_page"))


@main_bp.route("/reports/export")
@login_required
def export_report():
    path = Path(request.args.get("path", ""))

    resolved = path.resolve()

    if not _is_inside_export_dir(resolved) or not resolved.exists():
        abort(404)

    # Web/mobile keeps the normal browser download behavior. Only the desktop
    # private server uses native export behavior.
    if not is_desktop_request():
        return send_file(resolved, as_attachment=True)

    ok, message = export_report_file(resolved)
    log_action("Export Report", f"{resolved.name} - {message}")
    flash(message, "success" if ok else "warning")
    return redirect(url_for("main.reports_page"))


@main_bp.route("/reports/download")
@login_required
def download_report():
    path = Path(request.args.get("path", ""))

    resolved = path.resolve()

    if not _is_inside_export_dir(resolved) or not resolved.exists():
        abort(404)

    return send_file(resolved, as_attachment=True)


@main_bp.route("/reports/delete", methods=["POST"])
@login_required
def delete_report():
    path = Path(request.form.get("path", ""))

    resolved = path.resolve()

    if not _is_inside_export_dir(resolved) or not resolved.exists():
        abort(404)

    name = resolved.name
    resolved.unlink()

    log_action("Delete Report", f"Deleted report {name}")
    flash("Report deleted.", "info")
    return redirect(url_for("main.reports_page"))
