"""Markdown transcript rendering from persisted chat session data."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from core.constants import ASSISTANTMD_ROOT_DIR, CHAT_SESSIONS_DIR

from .chat_store import ChatStore, StoredChatMessage


def persist_chat_user_message(vault_path: str, session_id: str, prompt: str) -> str:
    """Persist the user prompt immediately so abrupt failures still leave a transcript trail."""
    history_file = _resolve_history_file(vault_path=vault_path, session_id=session_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(history_file, "a", encoding="utf-8") as handle:
        handle.write(f"*{timestamp}*\n\n")
        handle.write(f"**User:**\n {prompt}\n\n")
    return str(history_file)


def rewrite_chat_transcript(
    *,
    store: ChatStore,
    vault_path: str,
    vault_name: str,
    session_id: str,
) -> str:
    """Rewrite the chat transcript from the canonical persisted session store."""
    history_file = _resolve_history_file(vault_path=vault_path, session_id=session_id)
    messages = store.get_stored_messages(session_id=session_id, vault_name=vault_name)

    lines = [f"Chat Session: {session_id}", ""]
    for message in messages:
        if message.role not in ("user", "assistant"):
            continue
        lines.extend(_render_message_block(message))

    history_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(history_file)


def _render_message_block(message: StoredChatMessage) -> list[str]:
    timestamp = (message.created_at or "").strip() or "unknown time"
    label = _role_label(message.role)
    content = (message.content_text or "").rstrip()
    if not content:
        content = f"[{message.message_type}]"
    return [
        f"*{timestamp}*",
        "",
        f"**{label}:**",
        f" {content}",
        "",
    ]


def _role_label(role: str) -> str:
    normalized = (role or "").strip().lower()
    if normalized == "user":
        return "User"
    if normalized == "assistant":
        return "Assistant"
    if normalized == "system":
        return "System"
    if normalized == "tool":
        return "Tool"
    return normalized.title() or "Message"


def _resolve_history_file(*, vault_path: str, session_id: str) -> Path:
    """Return the transcript path for one session, creating parents when needed."""
    sessions_dir = Path(vault_path) / ASSISTANTMD_ROOT_DIR / CHAT_SESSIONS_DIR
    sessions_dir.mkdir(parents=True, exist_ok=True)

    safe_session_id = _sanitize_session_id(session_id)
    history_file = sessions_dir / f"{safe_session_id}.md"
    resolved_history = history_file.resolve()
    resolved_sessions = sessions_dir.resolve()
    if resolved_sessions not in resolved_history.parents:
        raise ValueError("Resolved chat history path is outside the chat sessions directory.")
    return history_file


def _sanitize_session_id(session_id: str) -> str:
    if not session_id:
        return "session"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", session_id)
    safe = safe.strip("._-")
    return safe or "session"
