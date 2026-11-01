# AI Expense Tracker

A single-user personal expense tracker built with Python, Streamlit, SQLAlchemy
and SQLite, with a Groq-powered AI assistant.

## Features

- Dashboard with monthly income, expenses, net cash flow and category chart
- Manual expense and income entry
- Transaction listing, editing and confirmation-protected deletion
- Active expense categories and category summaries
- AI assistant that can add, list, update and summarize transactions
- INR amounts stored as integer paise and Asia/Kolkata date interpretation
- SQLite schema initialized from the original single-user SQLAlchemy models

The AI assistant has no deletion tool. Deletion is available only in the
Transactions page, where it requires explicit confirmation.

## Requirements

- Python 3.10 or newer
- A Groq API key (https://console.groq.com/keys)
- Windows PowerShell, macOS Terminal or Linux shell

## Setup (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m pytest
$env:DATABASE_URL = "sqlite:///./data/expenses-single-user.db"
streamlit run app.py
```

Set `GROQ_API_KEY` in `.env` before using the AI assistant. The app works without
Google OAuth credentials or Streamlit authentication secrets.

## Setup (macOS / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
test -f .env || cp .env.example .env
python -m pytest
export DATABASE_URL="sqlite:///./data/expenses-single-user.db"
streamlit run app.py
```

## Database

The default database is `data/expenses-single-user.db`. The application creates
the original single-user tables and seeds the default expense categories when it
starts. It does not run Alembic migrations during startup. The baseline schema is
documented in [0001_initial_schema.py](./migrations/versions/0001_initial_schema.py).

The Google-authenticated branch uses a different, incompatible multi-user
database schema. To protect that database, this branch refuses to initialize a
database that contains a `users` table or `user_id` ownership columns. Point
`DATABASE_URL` at a new single-user database before starting this branch; do not
run a downgrade or clean-start migration against the existing database.

For example, to launch this branch with a separate local database in PowerShell:

```powershell
$env:DATABASE_URL = "sqlite:///./data/expenses-single-user.db"
streamlit run app.py
```

Money is stored as integer paise (`amount_paise`) to avoid floating-point
rounding; for example, ₹125.50 is stored as `12550`.

## Groq AI assistant

Create a Groq API key at https://console.groq.com/keys and set it in `.env`:

```env
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
GROQ_FALLBACK_MODELS=openai/gpt-oss-20b
```

The assistant can add expenses and income, retrieve transaction history,
calculate monthly and category summaries, and update existing transactions by
their exact IDs. Tool arguments are validated and dispatched through the
application services. Mutating tool calls are deduplicated within each request;
there is no AI delete tool.

The automated tests mock Groq and do not require an API key. An optional live
check can be run with:

```powershell
$env:RUN_GROQ_LIVE_TESTS = "1"
python -m pytest tests/test_groq_live.py -q
```

The live test uses an in-memory database and never accesses the local financial
database. Never commit `.env` or share your API key.

## Project layout

```text
ai-expense-tracker/
├── app.py
├── requirements.txt
├── .env.example
├── migrations/
│   └── versions/
│       └── 0001_initial_schema.py
├── agent/
│   ├── groq_client.py
│   ├── expense_tools.py
│   └── prompts.py
├── frontend/
│   └── chat.py
├── database/
│   ├── connection.py
│   ├── models.py
│   └── init_db.py
├── services/
│   ├── expense_service.py
│   └── income_service.py
├── utils/
│   ├── config.py
│   └── money.py
└── tests/
```
