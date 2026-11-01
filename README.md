# AI Expense Tracker

A multi-user expense tracker built with Python, Streamlit, SQLAlchemy and SQLite,
with an AI assistant powered by Groq and Google OpenID Connect authentication.

## Features

- Google OpenID Connect sign-in through Streamlit (`st.login`, `st.user`, `st.logout`)
- Users table keyed by Google's stable `sub` claim
- SQLite database with Alembic migrations
- SQLAlchemy models for users, categories, expenses, income, budgets,
  recurring transactions and agent conversations
- Required (`NOT NULL`) `user_id` ownership on expenses, income and AI chat records
- Every query, edit, delete and AI tool call is scoped to the signed-in user
- Seeded default expense categories
- Expense and income service functions
- Manual expense and income entry, editing and confirmed deletion
- AI assistant with Groq function/tool calling
- Automated tests with mocked Groq responses and authentication state

## Requirements

- Python 3.10 or newer
- A Groq API key (https://console.groq.com/keys)
- A Google OAuth 2.0 Web application client (Google Cloud Console)
- Windows PowerShell, macOS Terminal or Linux shell

## Setup (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
python -m pytest
streamlit run app.py
```

If PowerShell blocks virtual-environment activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Setup (macOS / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
python -m pytest
streamlit run app.py
```

## Authentication (Google OpenID Connect)

The app does not implement password authentication. Google is the identity
provider, and the stable Google `sub` claim is stored as the external identity in
`users.google_sub`. Email, name, given/family name, picture, locale and
`email_verified` are refreshed on each new login. The database user id is cached in
the Streamlit session; it is re-validated against the current `sub` on every rerun.

### Google Cloud Console configuration

1. Open https://console.cloud.google.com/ and create or select a project.
2. Configure **APIs & Services → OAuth consent screen**:
   - User type: External (or Internal for a Workspace-only app).
   - Add an app name, support email and developer contact.
   - Scopes: `openid`, `email`, `profile` (Streamlit requests these by default).
   - While the consent screen is in Testing, only listed test users can sign in.
3. Go to **APIs & Services → Credentials → Create credentials → OAuth client ID**
   and choose **Web application**.
4. Add authorized JavaScript origins:
   - `http://localhost:8501`
   - `https://<your-app>.streamlit.app` (production)
5. Add authorized redirect URIs. These must match `redirect_uri` exactly:
   - `http://localhost:8501/oauth2callback`
   - `https://<your-app>.streamlit.app/oauth2callback`
6. Copy the client ID and client secret into `.streamlit/secrets.toml`:

```toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "replace-with-a-long-random-string"
client_id = "your-google-client-id.apps.googleusercontent.com"
client_secret = "your-google-client-secret"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

Generate a strong cookie secret with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Never commit `.streamlit/secrets.toml`. For Streamlit Community Cloud, paste the
same `[auth]` block into the app's **Secrets** settings.

Google's OIDC metadata does not include an `end_session_endpoint`, so
`st.logout()` ends the app session but does not sign the user out of Google itself.

## Database and migrations

The default database is `data/expenses.db`. Money is stored as integer paise
(`amount_paise`) to avoid floating-point rounding; for example, ₹125.50 is stored as
`12550`.

Migrations are applied automatically when the app starts. The same can be done
manually:

```powershell
python -m database.init_db
alembic current
alembic history
```

A database created by the original single-user version has no `alembic_version`
table. The startup migration helper detects the existing `expenses` table, stamps it
at `0001_initial_schema` without changing data, then applies
`0002_multiuser_auth`.

Before migrating any important database, make a backup:

```powershell
Copy-Item data\expenses.db data\expenses.db.bak
```

Revision `0002_multiuser_auth` is additive only:

- creates `users` with a unique `google_sub`
- adds `user_id` columns and indexes to `expenses`, `income` and
  `agent_conversations`

Revision `0003_clean_start` performs the reviewed clean start:

- deletes **all** existing expense, income and AI conversation rows
- keeps the `users` table and the reusable default categories
- makes `user_id` `NOT NULL` on expenses, income and AI conversations
- recreates the owner foreign keys with `ON DELETE CASCADE` (a user's data is
  removed with the user) and keeps the category foreign keys and all indexes
- does **not** backfill ownership and does **not** assign old rows to the first user

The application now starts with zero financial transactions. Each user only sees
their own records. The migration is applied automatically on startup; to apply it
manually:

```powershell
Copy-Item data\expenses.db data\expenses.db.pre-clean-start.bak
python -m database.init_db
alembic current      # 0003_clean_start (head)
```

Downgrading `0003_clean_start` only makes `user_id` nullable again. It cannot
restore the deleted transactions; use the backup if those rows are still needed.

To roll back the multi-user revisions (restore the backup if you are unsure):

```powershell
alembic downgrade 0001_initial_schema
```

## Online deployment

- Use HTTPS and register the production `https://<app>/oauth2callback` redirect URI.
- Keep `client_id`, `client_secret`, `cookie_secret` and API keys in the hosting
  platform's secrets manager, never in Git.
- SQLite on Streamlit Community Cloud is ephemeral. For a real online deployment,
  point `DATABASE_URL` at a persistent PostgreSQL database and add a PostgreSQL
  driver (for example `psycopg[binary]`) to `requirements.txt`.
- Migrations run on startup; review the backup and migration plan before deploying.
- Financial data is isolated by user. All dashboard, transaction and AI assistant
  queries require the signed-in user's `user_id`.
- The clean-start migration deletes legacy transactions. On a hosted database,
  confirm the backup and run the migration during a maintenance window.

## Project layout

```text
ai-expense-tracker/
├── app.py
├── alembic.ini
├── requirements.txt
├── .env.example
├── .streamlit/
│   └── secrets.toml.example
├── auth/
│   └── streamlit_auth.py   # Google OIDC session handling and login UI
├── migrations/
│   ├── env.py
│   └── versions/
│       ├── 0001_initial_schema.py
│       ├── 0002_multiuser_auth.py
│       └── 0003_clean_start.py
├── agent/
│   ├── groq_client.py      # Groq Chat Completions + tool-calling loop
│   ├── expense_tools.py    # Tool schemas, validation and dispatch
│   └── prompts.py          # System prompt
├── frontend/
│   └── chat.py             # Streamlit chat UI
├── database/
│   ├── connection.py
│   ├── models.py
│   └── init_db.py
├── services/
│   ├── expense_service.py
│   ├── income_service.py
│   └── user_service.py
├── utils/
│   ├── config.py
│   └── money.py
├── tests/
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_user_service.py
│   ├── test_database.py
│   ├── test_agent_tools.py
│   ├── test_groq_client.py
│   └── test_groq_live.py
└── data/
```

## Notes

- SQLite is suitable for local development. Use a server database for a real
  multi-user online deployment.
- `alembic` now manages schema changes; do not run `create_all()` against a
  production database.
- This app does not connect to a bank, process payments or store banking credentials.
- It does not store Google passwords or OAuth tokens.

## Groq AI assistant

The AI Assistant page uses Groq's Chat Completions API and the official `groq`
Python SDK. It can add expenses and income, retrieve expenses and income, calculate
monthly/category summaries, and update an expense or income record by its exact ID.
Deletion remains on the Transactions page and requires the existing UI confirmation.

1. Create a Groq API key at https://console.groq.com/keys.
2. Add these values to `.env`:

```env
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
GROQ_FALLBACK_MODELS=openai/gpt-oss-20b
```

3. Install dependencies:

```powershell
pip install -r requirements.txt
```

4. Restart Streamlit:

```powershell
streamlit run app.py
```

### Changing models

The model is read from `GROQ_MODEL` at request time, so no Python code changes are
needed. The default is `openai/gpt-oss-120b`; to use the smaller model:

```env
GROQ_MODEL=openai/gpt-oss-20b
```

`GROQ_FALLBACK_MODELS` is an optional comma-separated list used only when the
primary model returns a transient error (timeout, rate limit or 5xx). It defaults
to `openai/gpt-oss-20b`.

### How tool calling works

1. The conversation history and OpenAI-compatible tool definitions are sent to Groq.
2. The assistant reply is checked for `tool_calls`.
3. Each call's JSON arguments are parsed and validated against the tool schema.
4. The matching allow-listed Python function runs through the existing services.
5. The assistant message (with its original tool calls) is appended to history.
6. Each result is appended as a `role: "tool"` message with its `tool_call_id`.
7. The updated conversation goes back to Groq until a normal answer is produced.

The loop is capped at 6 tool rounds. Identical mutating tool calls in the same turn
are executed once and their result is reused, so a repeated tool call cannot create
a duplicate transaction. There is no AI delete tool.

Never commit `.env` or share your API key. Groq usage is subject to the quotas and
billing terms of your Groq account. API keys are never logged or displayed; error
messages are redacted before they reach the UI.

### Optional live test

Automated tests mock Groq and never need a key. To run a real API check with the key
from your local `.env`:

```powershell
$env:RUN_GROQ_LIVE_TESTS = "1"
python -m pytest tests/test_groq_live.py -q
```

The live test is skipped automatically unless `RUN_GROQ_LIVE_TESTS=1` and a real
`GROQ_API_KEY` are configured. It uses an in-memory database, never `data/expenses.db`.

## Remaining hardening work

Authentication, schema preparation and per-user ownership isolation are complete.
Before inviting real users:

- Decide what should happen when an account is deleted. The owner foreign keys use
  `ON DELETE CASCADE`, so deleting a user removes that user's financial records.
- Add account deletion and data export flows if users need them.
- Persist AI chat records per user if conversation history should survive a
  browser session; the table and `user_id` column are already prepared.
- Move to PostgreSQL for an online deployment, configure backups and review
  deployment secrets.
- Add end-to-end tests with a real Google OIDC session in a staging environment.
