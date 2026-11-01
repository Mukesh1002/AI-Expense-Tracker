import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{(PROJECT_ROOT / 'data' / 'expenses-single-user.db').as_posix()}",
)
CURRENCY = os.getenv("CURRENCY", "INR")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

# Defaults used only when the matching environment variable is absent. The
# active model is always read from GROQ_MODEL at request time so it can be
# changed in .env without touching Python code.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_GROQ_FALLBACK_MODEL = "openai/gpt-oss-20b"

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
