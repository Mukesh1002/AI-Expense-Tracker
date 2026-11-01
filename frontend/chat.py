import streamlit as st

from agent.groq_client import get_model_name, run_groq_turn, sanitize_error_message
from database.connection import SessionLocal


def _show_chat_error(exc: Exception) -> str:
    """Show a sanitized, friendly error and return the fallback chat message."""
    error_text = sanitize_error_message(str(exc))
    lowered = error_text.lower()

    if "GROQ_API_KEY" in error_text:
        st.error(error_text)
    elif "rate limit" in lowered or "HTTP 429" in error_text:
        st.error("Groq is rate-limiting requests right now. Please wait a moment and try again.")
        st.caption(f"Diagnostic: {type(exc).__name__}: {error_text}")
    elif "time limit" in lowered or "timed out" in lowered or "timeout" in lowered:
        st.error("Groq did not respond in time. Please try again.")
        st.caption(f"Diagnostic: {type(exc).__name__}: {error_text}")
    elif "HTTP 401" in error_text or "HTTP 403" in error_text or "authentication" in lowered:
        st.error("Groq rejected the API key. Check GROQ_API_KEY in your .env file.")
        st.caption(f"Diagnostic: {type(exc).__name__}: {error_text}")
    elif "HTTP 503" in error_text or "unavailable" in lowered or "overloaded" in lowered:
        st.error(
            "Groq is busy right now, including the configured fallback model. "
            "Please try again shortly."
        )
        st.caption(f"Diagnostic: {type(exc).__name__}: {error_text}")
    else:
        st.error("I couldn't complete that request. Please try again.")
        st.caption(f"Diagnostic: {type(exc).__name__}: {error_text}")

    return "I couldn't complete that request. Please try again."


def render_chat():
    messages_key = "groq_chat_messages"
    history_key = "groq_chat_history"

    st.subheader("🤖 Personal Expense Assistant")
    st.caption(
        f"Powered by Groq · {get_model_name()} · "
        "Uses your existing local expense database"
    )

    if messages_key not in st.session_state:
        st.session_state[messages_key] = []
    if history_key not in st.session_state:
        st.session_state[history_key] = []

    with st.sidebar:
        if st.button(
            "Clear AI chat",
            key="clear_groq_chat",
        ):
            st.session_state[messages_key] = []
            st.session_state[history_key] = []
            st.rerun()

    for message in st.session_state[messages_key]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input(
        "Example: I spent ₹450 on dinner today",
        key="groq_chat_prompt",
    )
    if prompt:
        st.session_state[messages_key].append(
            {"role": "user", "content": prompt}
        )
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Groq is thinking..."):
                try:
                    with SessionLocal() as db:
                        answer, history = run_groq_turn(
                            db,
                            st.session_state[history_key],
                            prompt,
                        )
                    st.session_state[history_key] = history
                    st.markdown(answer)
                    st.session_state[messages_key].append(
                        {"role": "assistant", "content": answer}
                    )
                except Exception as exc:
                    fallback = _show_chat_error(exc)
                    st.session_state[messages_key].append(
                        {"role": "assistant", "content": fallback}
                    )
