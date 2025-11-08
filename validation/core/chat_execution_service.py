"""Chat execution service used by validation scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from core.logger import UnifiedLogger
from core.llm.session_manager import SessionManager
from core.llm.chat_executor import execute_chat_prompt


@dataclass
class ValidationChatResult:
    """Wrapper combining core chat result with resolved history path."""

    response: str
    session_id: str
    message_count: int
    history_file: Optional[str]


class ChatExecutionService:
    """Runs chat prompts against the core executor within test vaults."""

    def __init__(self, test_vaults_path: Path):
        self._test_vaults_path = test_vaults_path
        self._logger = UnifiedLogger(tag="validation-chat-service")
        self._session_manager = SessionManager()

    async def execute_prompt(
        self,
        *,
        vault: Path,
        vault_name: str,
        prompt: str,
        session_id: str,
        tools: Sequence[str],
        model: str,
        use_conversation_history: bool,
        instructions: Optional[str] = None,
    ) -> ValidationChatResult:
        """Execute chat prompt using the core chat executor."""

        if not vault.exists():
            raise FileNotFoundError(f"Vault not found for chat execution: {vault}")

        vault_path = str(vault)

        self._logger.info(
            "Executing chat prompt",
            vault=vault_name,
            session=session_id,
            tools=list(tools),
            model=model,
            use_history=use_conversation_history,
        )

        result = await execute_chat_prompt(
            vault_name=vault_name,
            vault_path=vault_path,
            prompt=prompt,
            session_id=session_id,
            tools=list(tools),
            model=model,
            use_conversation_history=use_conversation_history,
            session_manager=self._session_manager,
            instructions=instructions,
        )

        return ValidationChatResult(
            response=result.response,
            session_id=result.session_id,
            message_count=result.message_count,
            history_file=result.history_file,
        )

    def clear_session(self, vault_name: str, session_id: str) -> None:
        """Clear conversation history for a specific session."""
        self._session_manager.clear_history(session_id=session_id, vault_name=vault_name)
