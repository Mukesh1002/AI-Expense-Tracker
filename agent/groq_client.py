"""Groq Chat Completions client with OpenAI-compatible function calling.

The assistant only ever executes allow-listed Python tools from
``agent.expense_tools``; it never receives SQL access and it has no delete tool.
"""

import json
import os
import re
import time

from groq import APIConnectionError, APITimeoutError, Groq, RateLimitError

from agent.expense_tools import TOOL_DEFINITIONS, execute_tool, validate_tool_arguments
from agent.prompts import build_system_prompt
from utils.config import DEFAULT_GROQ_FALLBACK_MODEL, DEFAULT_GROQ_MODEL

REQUEST_TIMEOUT_SECONDS = 20.0
TURN_TIMEOUT_SECONDS = 45.0
MAX_TOOL_ROUNDS = 6
MAX_REQUEST_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 1.0
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}

EMPTY_RESPONSE_MESSAGE = "I couldn't generate a response. Please try again."
MAX_ROUNDS_MESSAGE = (
    "I stopped because this request needed more tool steps than the safety limit "
    "allows. Please check the Transactions page and ask again with a narrower request."
)

# Calls that change data must never run twice for the same arguments in one turn.
MUTATING_TOOLS = {"add_expense", "add_income", "update_expense", "update_income"}


class GroqRequestError(RuntimeError):
    """A Groq API request failed with a sanitized diagnostic."""


class GroqResponseError(RuntimeError):
    """Groq returned a response that the chat client cannot process."""


def sanitize_error_message(message) -> str:
    """Redact credentials and collapse whitespace before showing an error."""
    text = str(message or "")
    api_key = os.getenv("GROQ_API_KEY")
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = re.sub(r"\bgsk_[A-Za-z0-9_-]{10,}\b", "[REDACTED]", text)
    text = re.sub(
        r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;\"']+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;\"']+",
        r"\1[REDACTED]",
        text,
    )
    return text.replace("\r", " ").replace("\n", " ")[:700]


def get_model_name() -> str:
    """Active model, read from the environment at call time."""
    configured = (os.getenv("GROQ_MODEL") or "").strip()
    return configured or DEFAULT_GROQ_MODEL


def _model_candidates() -> list[str]:
    primary = get_model_name()
    raw_fallbacks = (os.getenv("GROQ_FALLBACK_MODELS") or "").strip()
    if raw_fallbacks:
        fallbacks = [item.strip() for item in raw_fallbacks.split(",")]
    else:
        fallbacks = [DEFAULT_GROQ_FALLBACK_MODEL]
    candidates = [primary]
    for model in fallbacks:
        if model and model != primary and model not in candidates:
            candidates.append(model)
    return candidates


def _get_client():
    api_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not api_key or api_key.lower() in {"your_groq_api_key", "changeme"}:
        raise RuntimeError(
            "GROQ_API_KEY is missing. Add it to your .env file and restart the app."
        )
    return Groq(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError)):
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code in RETRYABLE_STATUS_CODES


def _request_error(exc: Exception, models: list[str]) -> GroqRequestError:
    status_code = getattr(exc, "status_code", None)
    details = [f"Groq API request failed ({type(exc).__name__})"]
    if status_code is not None:
        details.append(f"HTTP {status_code}")
    if isinstance(exc, RateLimitError) or status_code == 429:
        details.append("rate limit reached")
    if isinstance(exc, APITimeoutError) or status_code == 408:
        details.append("request timed out")
    details.append(f"model(s) tried: {', '.join(models)}")
    diagnostic = sanitize_error_message(str(exc)) or "no additional details"
    return GroqRequestError(f"{', '.join(details)}: {diagnostic}")


def _create_completion(client, messages: list[dict], deadline: float):
    """Send one chat-completions request, with bounded retries and model fallback."""
    models = _model_candidates()
    attempted: list[str] = []
    last_error: Exception | None = None

    for model in models:
        attempted.append(model)
        for attempt in range(MAX_REQUEST_ATTEMPTS):
            if time.monotonic() >= deadline:
                raise GroqRequestError(
                    f"Groq request exceeded the {TURN_TIMEOUT_SECONDS:.0f}-second time limit."
                )
            try:
                return client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": build_system_prompt()},
                        *messages,
                    ],
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                    temperature=0.2,
                )
            except Exception as exc:  # SDK errors, plus network/serialization errors
                last_error = exc
                if not _is_retryable(exc):
                    raise _request_error(exc, attempted) from None
                if attempt + 1 < MAX_REQUEST_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

    if last_error is None:
        raise GroqRequestError("Groq request failed without an error response.")
    error = _request_error(last_error, attempted)
    if len(attempted) > 1:
        raise GroqRequestError(
            f"{error} (configured fallback models were also unavailable)"
        ) from None
    raise error from None


def _response_message(response):
    choices = getattr(response, "choices", None)
    if not choices:
        raise GroqResponseError("Groq returned no response choices.")
    message = getattr(choices[0], "message", None)
    if message is None:
        raise GroqResponseError("Groq returned a response without a message.")
    return message


def _parse_tool_arguments(raw_arguments) -> dict:
    if raw_arguments is None or raw_arguments == "":
        return {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not isinstance(raw_arguments, str):
        raise ValueError("Tool arguments must be a JSON object.")
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON arguments: {exc.msg}.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    return parsed


def _call_cache_key(name: str, args: dict) -> str:
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


def _assistant_tool_message(message, calls: list[dict]) -> dict:
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"],
                },
            }
            for call in calls
        ],
    }


def _serialize_calls(message, round_index: int) -> list[dict]:
    calls = []
    for index, tool_call in enumerate(getattr(message, "tool_calls", None) or []):
        function = getattr(tool_call, "function", None)
        name = getattr(function, "name", None) if function is not None else None
        arguments = getattr(function, "arguments", None) if function is not None else None
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {}, ensure_ascii=False, default=str)
        calls.append(
            {
                "id": getattr(tool_call, "id", None) or f"call_{round_index}_{index}",
                "name": name or "",
                "arguments": arguments,
            }
        )
    return calls


def _execute_call(
    db, name: str, raw_arguments, executed: dict[str, dict], *, user_id: int
) -> dict:
    try:
        args = _parse_tool_arguments(raw_arguments)
        args = validate_tool_arguments(name, args)
    except ValueError as exc:
        return {"success": False, "error": sanitize_error_message(str(exc))}

    cache_key = _call_cache_key(name, args)
    if name in MUTATING_TOOLS and cache_key in executed:
        cached = dict(executed[cache_key])
        cached["note"] = (
            "Identical call already executed in this turn; its result was reused "
            "instead of running the transaction again."
        )
        return cached

    try:
        result = execute_tool(db, name, args, user_id=user_id)
    except Exception as exc:
        if db is not None:
            db.rollback()
        result = {
            "success": False,
            "error": sanitize_error_message(str(exc)) or type(exc).__name__,
        }

    if name in MUTATING_TOOLS:
        executed[cache_key] = result
    return result


def run_groq_turn(
    db,
    history: list[dict],
    user_message: str,
    *,
    user_id: int,
) -> tuple[str, list[dict]]:
    """Run one chat turn, executing only explicitly allow-listed application tools.

    Every tool call is scoped to ``user_id`` so the model can only read or
    change the signed-in user's records. ``history`` is the plain OpenAI-style
    message list returned by the previous turn. The system prompt is added fresh
    to every request and is not stored in the returned history.
    """
    client = _get_client()
    messages: list[dict] = [dict(item) for item in (history or [])]
    messages.append({"role": "user", "content": user_message})
    deadline = time.monotonic() + TURN_TIMEOUT_SECONDS
    executed: dict[str, dict] = {}

    for round_index in range(MAX_TOOL_ROUNDS):
        response = _create_completion(client, messages, deadline)
        message = _response_message(response)
        calls = _serialize_calls(message, round_index)

        if not calls:
            answer = (message.content or "").strip() or EMPTY_RESPONSE_MESSAGE
            messages.append({"role": "assistant", "content": answer})
            return answer, messages

        messages.append(_assistant_tool_message(message, calls))

        for call in calls:
            result = _execute_call(
                db, call["name"], call["arguments"], executed, user_id=user_id
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

    messages.append({"role": "assistant", "content": MAX_ROUNDS_MESSAGE})
    return MAX_ROUNDS_MESSAGE, messages
