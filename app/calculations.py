from decimal import Decimal, ROUND_HALF_UP


def money(value) -> Decimal:
    if value is None or value == "":
        value = "0"
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_transaction(
    kilos_milled,
    milling_rate_per_kg,
    has_chaff_deduction=False,
    chaff_kilos=0,
    chaff_rate_per_kg=0,
    amount_paid=0
):
    kilos = money(kilos_milled)
    milling_rate = money(milling_rate_per_kg)
    paid = money(amount_paid)

    gross_fee = money(kilos * milling_rate)

    if has_chaff_deduction:
        ck = money(chaff_kilos)
        cr = money(chaff_rate_per_kg)
        chaff_deduction = money(ck * cr)
    else:
        ck = money(0)
        cr = money(0)
        chaff_deduction = money(0)

    net_amount = money(gross_fee - chaff_deduction)

    # Amount paid can never exceed the amount owed; capping here prevents an
    # over-payment from inflating "cash collected" totals and reports.
    if net_amount >= 0 and paid > net_amount:
        paid = net_amount

    balance = money(net_amount - paid)

    if balance <= 0:
        status = "Paid"
        balance = money(0)
    elif paid <= 0:
        status = "Unpaid"
    else:
        status = "Partial"

    return {
        "kilos_milled": kilos,
        "milling_rate_per_kg": milling_rate,
        "gross_fee": gross_fee,
        "has_chaff_deduction": bool(has_chaff_deduction),
        "chaff_kilos": ck,
        "chaff_rate_per_kg": cr,
        "chaff_deduction": chaff_deduction,
        "net_amount": net_amount,
        "amount_paid": paid,
        "balance": balance,
        "payment_status": status,
    }


def compute_commercial_transaction(number_of_sacks, price_per_sack, amount_paid=0, total_amount=None):
    sacks = money(number_of_sacks)
    sack_price = money(price_per_sack)
    paid = money(amount_paid)

    total = money(total_amount) if total_amount not in (None, "") else money(sacks * sack_price)

    # Amount paid can never exceed the total owed (prevents over-payment from
    # inflating collected-cash totals and reports).
    if total >= 0 and paid > total:
        paid = total

    balance = money(total - paid)

    if balance <= 0:
        status = "Paid"
        balance = money(0)
    elif paid <= 0:
        status = "Unpaid"
    else:
        status = "Partial"

    return {
        "number_of_sacks": sacks,
        "price_per_sack": sack_price,
        "total_amount": total,
        "amount_paid": paid,
        "balance": balance,
        "payment_status": status,
    }


def format_money(value, symbol="₱") -> str:
    return f"{symbol}{money(value):,.2f}"
