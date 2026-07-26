"""API projections for durable vault activity."""

from typing import Literal, cast

from core.vault_state.service import VaultActivityGroup

from ..models import VaultActivityGroupInfo, VaultMutationInfo
from .shared import chat_store


def vault_activity_group_info(group: VaultActivityGroup) -> VaultActivityGroupInfo:
    """Project one durable activity group into its API representation."""
    chat_session = None
    if group.activity_kind == "chat" and group.chat_session_id:
        chat_session = chat_store.get_session(group.chat_session_id, group.vault_name)
    return VaultActivityGroupInfo(
        activity_id=group.activity_id,
        activity_kind=group.activity_kind,
        activity_label=group.activity_label,
        chat_session_id=group.chat_session_id,
        chat_session_title=(
            chat_session.title if chat_session else group.chat_session_title
        ),
        chat_session_created_at=(
            chat_session.created_at if chat_session else group.chat_session_created_at
        ),
        chat_session_last_activity_at=(
            chat_session.last_activity_at
            if chat_session
            else group.chat_session_last_activity_at
        ),
        status=group.status,
        rollback_status=group.rollback_status,
        task_id=group.task_id,
        task_kind=group.task_kind,
        task_source=group.task_source,
        task_scope=group.task_scope,
        task_label=group.task_label,
        goal_id=group.goal_id,
        step_id=group.step_id,
        vault_id=group.vault_id,
        vault_name=group.vault_name,
        mutation_count=group.mutation_count,
        operation_count=group.operation_count,
        first_mutation_at=group.first_mutation_at,
        last_mutation_at=group.last_mutation_at,
        expires_at=group.expires_at,
        mutations=[
            VaultMutationInfo(
                id=mutation.id,
                activity_id=mutation.activity_id,
                operation_id=mutation.operation_id,
                task_id=mutation.task_id,
                task_kind=mutation.task_kind,
                task_source=mutation.task_source,
                task_scope=mutation.task_scope,
                task_label=mutation.task_label,
                goal_id=mutation.goal_id,
                step_id=mutation.step_id,
                path=mutation.path,
                related_path=mutation.related_path,
                target_kind=cast(Literal["file", "directory"], mutation.target_kind),
                operation=mutation.operation,
                status=mutation.status,
                event_sequence=mutation.event_sequence,
                before_exists=mutation.before_exists,
                before_hash=mutation.before_hash,
                before_snapshot_id=mutation.before_snapshot_id,
                after_exists=mutation.after_exists,
                after_hash=mutation.after_hash,
                after_snapshot_id=mutation.after_snapshot_id,
                snapshot_ref=mutation.snapshot_ref,
                created_at=mutation.created_at,
                expires_at=mutation.expires_at,
                metadata=mutation.metadata,
            )
            for mutation in group.mutations
        ],
    )
