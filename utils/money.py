from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

def rupees_to_paise(amount: str | int | float | Decimal) -> int:
    """Convert a rupee amount to integer paise without binary-float arithmetic."""
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Enter a valid monetary amount.") from exc

    if value <= 0:
        raise ValueError("Amount must be greater than zero.")
    return int(value * 100)

def paise_to_rupees(amount_paise: int) -> Decimal:
    return (Decimal(amount_paise) / Decimal(100)).quantize(Decimal("0.01"))
