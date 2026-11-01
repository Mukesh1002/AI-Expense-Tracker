from datetime import date

from sqlalchemy import func, select

from database.models import Category, Expense, Income
from services.expense_service import add_expense, list_expenses, update_expense
from services.income_service import add_income, list_incomes, update_income
from utils.money import paise_to_rupees

PAYMENT_METHODS = ["UPI", "Cash", "Debit Card", "Credit Card", "Net Banking", "Other"]


def _string(description: str) -> dict:
    return {"type": "string", "description": description}


def _number(description: str) -> dict:
    return {"type": "number", "description": description}


def _integer(description: str) -> dict:
    return {"type": "integer", "description": description}


# Single source of truth for the tools exposed to the AI. The Groq client turns
# these into OpenAI-compatible function definitions, and the same schemas are
# used to validate the arguments the model sends back.
TOOL_SCHEMAS: dict[str, dict] = {
    "list_expense_categories": {
        "description": "List the active expense categories accepted by the application.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "add_expense": {
        "description": "Record a new expense. Amount is in INR rupees.",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": _number("Expense amount in INR rupees"),
                "description": _string("What the expense was for"),
                "category": _string("An existing expense category"),
                "expense_date": _string("Date in YYYY-MM-DD format"),
                "payment_method": _string(
                    "One of: " + ", ".join(PAYMENT_METHODS)
                ),
                "notes": _string("Optional notes"),
            },
            "required": ["amount", "description", "category", "expense_date"],
            "additionalProperties": False,
        },
    },
    "add_income": {
        "description": "Record received income. Amount is in INR rupees.",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": _number("Income amount in INR rupees"),
                "source": _string("Income source, such as salary"),
                "income_date": _string("Date in YYYY-MM-DD format"),
                "notes": _string("Optional notes"),
            },
            "required": ["amount", "source", "income_date"],
            "additionalProperties": False,
        },
    },
    "get_expenses": {
        "description": "Retrieve expenses, optionally between two dates. Returns up to 100 records.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": _string("Optional start date YYYY-MM-DD"),
                "end_date": _string("Optional end date YYYY-MM-DD"),
            },
            "additionalProperties": False,
        },
    },
    "get_incomes": {
        "description": "Retrieve income records, optionally between two dates. Returns up to 100 records.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": _string("Optional start date YYYY-MM-DD"),
                "end_date": _string("Optional end date YYYY-MM-DD"),
            },
            "additionalProperties": False,
        },
    },
    "get_monthly_summary": {
        "description": "Calculate income, expenses and net cash flow for a calendar month.",
        "parameters": {
            "type": "object",
            "properties": {
                "month": _integer("Month number 1 to 12"),
                "year": _integer("Four digit year"),
            },
            "required": ["month", "year"],
            "additionalProperties": False,
        },
    },
    "get_category_summary": {
        "description": "Calculate expense totals grouped by category for a calendar month.",
        "parameters": {
            "type": "object",
            "properties": {
                "month": _integer("Month number 1 to 12"),
                "year": _integer("Four digit year"),
            },
            "required": ["month", "year"],
            "additionalProperties": False,
        },
    },
    "update_expense": {
        "description": (
            "Update an existing expense by its exact database ID. Use get_expenses first "
            "if the ID is unknown. All editable fields are required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expense_id": _integer("Exact expense ID"),
                "amount": _number("New amount in INR rupees"),
                "description": _string("New description"),
                "category": _string("Existing expense category"),
                "expense_date": _string("New date YYYY-MM-DD"),
                "payment_method": _string(
                    "One of: " + ", ".join(PAYMENT_METHODS)
                ),
                "notes": _string("Optional notes"),
            },
            "required": [
                "expense_id",
                "amount",
                "description",
                "category",
                "expense_date",
            ],
            "additionalProperties": False,
        },
    },
    "update_income": {
        "description": (
            "Update an existing income record by its exact database ID. Use get_incomes "
            "first if the ID is unknown. All editable fields are required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "income_id": _integer("Exact income ID"),
                "amount": _number("New amount in INR rupees"),
                "source": _string("New income source"),
                "income_date": _string("New date YYYY-MM-DD"),
                "notes": _string("Optional notes"),
            },
            "required": ["income_id", "amount", "source", "income_date"],
            "additionalProperties": False,
        },
    },
}

# There is deliberately no delete tool. Deletion stays on the Transactions page,
# behind the existing confirmation checkbox.
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {"name": name, **schema},
    }
    for name, schema in TOOL_SCHEMAS.items()
]


def _coerce_value(tool: str, field: str, expected_type: str, value):
    if expected_type == "number":
        if isinstance(value, bool):
            raise ValueError(f"Argument '{field}' for {tool} must be a number.")
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
        raise ValueError(f"Argument '{field}' for {tool} must be a number.")

    if expected_type == "integer":
        if isinstance(value, bool):
            raise ValueError(f"Argument '{field}' for {tool} must be an integer.")
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                number = float(value.strip())
            except ValueError:
                number = None
            if number is not None and number.is_integer():
                return int(number)
        raise ValueError(f"Argument '{field}' for {tool} must be an integer.")

    if expected_type == "string":
        if isinstance(value, str):
            return value
        raise ValueError(f"Argument '{field}' for {tool} must be a string.")

    return value


def validate_tool_arguments(name: str, args) -> dict:
    """Validate and normalise model-supplied arguments against the tool schema.

    Raises ValueError with a user-safe message when the call cannot be executed.
    """
    schema = TOOL_SCHEMAS.get(name)
    if schema is None:
        raise ValueError(f"Unsupported tool: {name}")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be a JSON object.")

    parameters = schema["parameters"]
    properties = parameters.get("properties", {})
    cleaned = {}

    for field in parameters.get("required", []):
        value = args.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"Missing required argument '{field}' for {name}.")

    for field, spec in properties.items():
        if field not in args:
            continue
        value = args[field]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        cleaned[field] = _coerce_value(name, field, spec.get("type"), value)

    return cleaned


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Date must be in YYYY-MM-DD format.") from exc


def execute_tool(db, name: str, args: dict) -> dict:
    """Dispatch an allow-listed AI tool call through the application services."""
    args = validate_tool_arguments(name, args)

    if name == "list_expense_categories":
        categories = db.scalars(
            select(Category.name)
            .where(Category.type == "EXPENSE", Category.is_active.is_(True))
            .order_by(Category.name)
        ).all()
        return {"categories": list(categories)}

    if name == "add_expense":
        item = add_expense(
            db,
            amount=args["amount"],
            description=args["description"],
            category_name=args["category"],
            expense_date=_date(args["expense_date"]),
            payment_method=args.get("payment_method"),
            notes=args.get("notes"),
            source="AI_CHAT",
        )
        return {
            "success": True,
            "id": item.id,
            "amount": str(paise_to_rupees(item.amount_paise)),
            "description": item.description,
            "category": item.category.name,
            "date": item.expense_date.isoformat(),
            "payment_method": item.payment_method,
        }

    if name == "add_income":
        item = add_income(
            db,
            amount=args["amount"],
            source=args["source"],
            income_date=_date(args["income_date"]),
            notes=args.get("notes"),
        )
        return {
            "success": True,
            "id": item.id,
            "amount": str(paise_to_rupees(item.amount_paise)),
            "source": item.source,
            "date": item.income_date.isoformat(),
        }

    if name == "get_expenses":
        start = _date(args["start_date"]) if args.get("start_date") else None
        end = _date(args["end_date"]) if args.get("end_date") else None
        rows = list_expenses(db, start_date=start, end_date=end)
        return {
            "expenses": [
                {
                    "id": row.id,
                    "amount": str(paise_to_rupees(row.amount_paise)),
                    "description": row.description,
                    "category": row.category.name,
                    "date": row.expense_date.isoformat(),
                    "payment_method": row.payment_method,
                }
                for row in rows[:100]
            ],
            "returned_count": min(len(rows), 100),
            "total_matching": len(rows),
        }

    if name == "get_incomes":
        start = _date(args["start_date"]) if args.get("start_date") else None
        end = _date(args["end_date"]) if args.get("end_date") else None
        rows = list_incomes(db, start_date=start, end_date=end)
        return {
            "incomes": [
                {
                    "id": row.id,
                    "amount": str(paise_to_rupees(row.amount_paise)),
                    "source": row.source,
                    "date": row.income_date.isoformat(),
                    "notes": row.notes,
                }
                for row in rows[:100]
            ],
            "returned_count": min(len(rows), 100),
            "total_matching": len(rows),
        }

    if name == "get_monthly_summary":
        month = int(args["month"])
        year = int(args["year"])
        if month < 1 or month > 12:
            raise ValueError("Month must be between 1 and 12.")
        start = date(year, month, 1)
        end = date(year + (month == 12), (month % 12) + 1, 1)
        expenses = db.scalar(
            select(func.coalesce(func.sum(Expense.amount_paise), 0))
            .where(
                Expense.expense_date >= start,
                Expense.expense_date < end,
            )
        ) or 0
        income = db.scalar(
            select(func.coalesce(func.sum(Income.amount_paise), 0))
            .where(
                Income.income_date >= start,
                Income.income_date < end,
            )
        ) or 0
        count = db.scalar(
            select(func.count(Expense.id))
            .where(
                Expense.expense_date >= start,
                Expense.expense_date < end,
            )
        ) or 0
        return {
            "month": month,
            "year": year,
            "total_expenses": str(paise_to_rupees(expenses)),
            "total_income": str(paise_to_rupees(income)),
            "net_cash_flow": str(paise_to_rupees(income - expenses)),
            "expense_count": count,
        }

    if name == "get_category_summary":
        month = int(args["month"])
        year = int(args["year"])
        if month < 1 or month > 12:
            raise ValueError("Month must be between 1 and 12.")
        start = date(year, month, 1)
        end = date(year + (month == 12), (month % 12) + 1, 1)
        rows = db.execute(
            select(Category.name, func.sum(Expense.amount_paise), func.count(Expense.id))
            .join(Expense, Expense.category_id == Category.id)
            .where(
                Expense.expense_date >= start,
                Expense.expense_date < end,
            )
            .group_by(Category.name)
            .order_by(func.sum(Expense.amount_paise).desc())
        ).all()
        return {
            "month": month,
            "year": year,
            "categories": [
                {"category": name, "amount": str(paise_to_rupees(total)), "count": count}
                for name, total, count in rows
            ],
        }

    if name == "update_expense":
        item = update_expense(
            db,
            int(args["expense_id"]),
            amount=args["amount"],
            description=args["description"],
            category_name=args["category"],
            expense_date=_date(args["expense_date"]),
            payment_method=args.get("payment_method"),
            notes=args.get("notes"),
        )
        return {
            "success": True,
            "id": item.id,
            "amount": str(paise_to_rupees(item.amount_paise)),
            "description": item.description,
            "category": item.category.name,
            "date": item.expense_date.isoformat(),
        }

    if name == "update_income":
        item = update_income(
            db,
            int(args["income_id"]),
            amount=args["amount"],
            source=args["source"],
            income_date=_date(args["income_date"]),
            notes=args.get("notes"),
        )
        return {
            "success": True,
            "id": item.id,
            "amount": str(paise_to_rupees(item.amount_paise)),
            "source": item.source,
            "date": item.income_date.isoformat(),
        }

    raise ValueError(f"Unsupported tool: {name}")
