"""Integration scenario for collaborative edit proposal artifacts."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.chat.chat_store import ChatStore
from core.chat.edit_proposals import create_edit_proposal
from validation.core.base_scenario import BaseScenario


class EditProposalArtifactsScenario(BaseScenario):
    """Validate edit proposal artifact creation, API fetch, apply, and conflict handling."""

    async def test_scenario(self):
        vault = self.create_vault("EditProposalArtifactsVault")
        self.create_file(
            vault,
            "Projects/Alpha/README.md",
            "# Alpha\n\nStatus: Draft\n\nNext: Write summary.\n",
        )
        self.create_file(vault, "Projects/Alpha/DeleteMe.md", "Remove this note.\n")
        self.create_file(vault, "Projects/Alpha/MoveMe.md", "Move this note.\n")
        self.create_file(vault, "Projects/Alpha/ContentAlias.md", "Line one\nLine two old\n")

        await self.start_system()

        session_id = "edit_proposal_artifacts_session"
        store = ChatStore(system_root=str(self._get_system_controller()._system_root))
        store.ensure_session(session_id, vault.name)

        def create_proposal(*, edits, title="", summary=""):
            return create_edit_proposal(
                vault_name=vault.name,
                vault_path=vault,
                session_id=session_id,
                edits=edits,
                title=title,
                summary=summary,
            )

        create_checkpoint = self.event_checkpoint()
        result = create_proposal(
            edits=[
                {
                    "path": "Projects/Alpha/README.md",
                    "original_text": "Status: Draft",
                    "replacement_text": "Status: Reviewed",
                    "rationale": "Mark the note as reviewed.",
                }
            ],
            title="Review README status",
            summary="One focused status update.",
        )
        assert result["artifact_ref"], "Stored proposal should return an artifact ref"
        artifact_ref = result["artifact_ref"]
        self.assert_event_contains(
            self.events_since(create_checkpoint),
            name="edit_proposal_created",
            expected={
                "vault_name": vault.name,
                "session_id": session_id,
                "artifact_ref": artifact_ref,
                "edit_count": 1,
            },
        )

        fetched = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{artifact_ref}"
        )
        assert fetched.status_code == 200, "Stored proposal should be fetchable through the API"
        proposal = fetched.json()
        assert proposal["artifact_ref"] == artifact_ref, "Fetched proposal should preserve artifact ref"
        assert proposal["status"] == "pending", "New proposal should start pending"
        assert proposal["edits"][0]["before_sha256"], "Proposal should capture the pre-edit file hash"

        apply_checkpoint = self.event_checkpoint()
        applied = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{artifact_ref}/apply",
            method="POST",
            data={
                "selected_edit_ids": [proposal["edits"][0]["edit_id"]],
                "replacement_overrides": {
                    proposal["edits"][0]["edit_id"]: "Status: Approved",
                },
            },
        )
        assert applied.status_code == 200, "Selected proposal edits should apply"
        assert applied.json()["status"] == "applied", "Apply response should mark proposal applied"
        assert (vault / "Projects/Alpha/README.md").read_text(encoding="utf-8") == (
            "# Alpha\n\nStatus: Approved\n\nNext: Write summary.\n"
        ), "Apply should write the user-edited replacement text"
        applied_history = store.get_stored_messages(session_id, vault.name)
        assert applied_history[-2].role == "user", "Apply should append a user-readable approval record"
        assert applied_history[-1].role == "assistant", "Apply should append a paired assistant confirmation"
        assert "Approved and applied edit proposal" in applied_history[-2].content_text, (
            "Apply history should record that the proposal was accepted"
        )
        assert f"Edit `{proposal['edits'][0]['edit_id']}`" in applied_history[-2].content_text, (
            "Apply history should list applied edit ids"
        )
        assert "Applied the approved edits." in applied_history[-1].content_text, (
            "Apply history should include a completed assistant turn"
        )

        content_alias_result = create_proposal(
            edits=[
                {
                    "operation": "replace_text",
                    "path": "Projects/Alpha/ContentAlias.md",
                    "original_text": "Line one\nLine two old\n",
                    "content": "Line one\nLine two new\n",
                    "rationale": "Use content as replacement text.",
                }
            ],
            title="Content alias replacement",
        )
        content_alias_ref = content_alias_result["artifact_ref"]
        content_alias_proposal = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{content_alias_ref}"
        ).json()
        content_alias_edit = content_alias_proposal["edits"][0]
        assert content_alias_edit["replacement_text"] == "Line one\nLine two new\n", (
            "replace_text proposals should accept content as replacement_text"
        )
        content_alias_apply = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{content_alias_ref}/apply",
            method="POST",
            data={"selected_edit_ids": [content_alias_edit["edit_id"]]},
        )
        assert content_alias_apply.status_code == 200, (
            "replace_text proposal using content should apply"
        )
        assert (vault / "Projects/Alpha/ContentAlias.md").read_text(encoding="utf-8") == (
            "Line one\nLine two new\n"
        ), "content alias should be written as replacement text"

        self.assert_event_contains(
            self.events_since(apply_checkpoint),
            name="vault_state_mutation_untracked",
            expected={
                "vault_name": vault.name,
                "path": "Projects/Alpha/README.md",
                "operation": "apply_edit_proposal",
                "reason": "missing_execution_task_context",
            },
        )

        second = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{artifact_ref}/apply",
            method="POST",
            data={"selected_edit_ids": [proposal["edits"][0]["edit_id"]]},
        )
        assert second.status_code == 409, "Already-applied proposal should reject repeated apply"
        assert second.json().get("error") == "ProposalAlreadyApplied", (
            "Repeated apply should use a stable conflict error"
        )

        conflict_result = create_proposal(
            edits=[
                {
                    "path": "Projects/Alpha/README.md",
                    "original_text": "Next: Write summary.",
                    "replacement_text": "Next: Publish summary.",
                }
            ],
        )
        conflict_ref = conflict_result["artifact_ref"]
        (vault / "Projects/Alpha/README.md").write_text(
            "# Alpha\n\nStatus: Approved\n\nNext: Changed elsewhere.\n",
            encoding="utf-8",
        )
        conflict_proposal = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{conflict_ref}"
        ).json()
        conflict = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{conflict_ref}/apply",
            method="POST",
            data={"selected_edit_ids": [conflict_proposal["edits"][0]["edit_id"]]},
        )
        assert conflict.status_code == 409, "Changed file should reject stale proposal apply"
        assert conflict.json().get("error") == "VaultFileConflict", (
            "Stale proposal apply should use the vault conflict error"
        )

        operation_result = create_proposal(
            edits=[
                {
                    "operation": "create_file",
                    "path": "Projects/Alpha/NewProposal.md",
                    "replacement_text": "# Created\n\nFrom proposal.\n",
                    "rationale": "Create a new note.",
                },
                {
                    "operation": "delete_file",
                    "path": "Projects/Alpha/DeleteMe.md",
                    "rationale": "Remove the stale note.",
                },
                {
                    "operation": "move_file",
                    "path": "Projects/Alpha/MoveMe.md",
                    "destination": "Projects/Alpha/Moved.md",
                    "rationale": "Rename the note.",
                },
            ],
            title="Create delete move",
        )
        operation_ref = operation_result["artifact_ref"]
        operation_proposal = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{operation_ref}"
        ).json()
        operation_ids = [edit["edit_id"] for edit in operation_proposal["edits"]]
        operation_apply = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{operation_ref}/apply",
            method="POST",
            data={
                "selected_edit_ids": operation_ids,
                "replacement_overrides": {
                    operation_ids[0]: "# Created\n\nEdited before approval.\n",
                    operation_ids[2]: "Projects/Alpha/MovedAndEdited.md",
                },
            },
        )
        assert operation_apply.status_code == 200, "Create/delete/move proposal should apply"
        assert (vault / "Projects/Alpha/NewProposal.md").read_text(encoding="utf-8") == (
            "# Created\n\nEdited before approval.\n"
        ), "Create proposal should write approved user-edited content"
        assert not (vault / "Projects/Alpha/DeleteMe.md").exists(), (
            "Delete proposal should remove the approved file"
        )
        assert not (vault / "Projects/Alpha/MoveMe.md").exists(), (
            "Move proposal should remove the source file"
        )
        assert (vault / "Projects/Alpha/MovedAndEdited.md").read_text(encoding="utf-8") == (
            "Move this note.\n"
        ), "Move proposal should use the approved destination override"

        deny_result = create_proposal(
            edits=[
                {
                    "path": "Projects/Alpha/README.md",
                    "original_text": "Status: Approved",
                    "replacement_text": "Status: Rejected",
                }
            ],
        )
        deny_ref = deny_result["artifact_ref"]
        deny_checkpoint = self.event_checkpoint()
        denied = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{deny_ref}/deny",
            method="POST",
        )
        assert denied.status_code == 200, "Proposal deny should succeed without writing files"
        assert denied.json().get("status") == "denied", "Deny response should mark proposal denied"
        assert (vault / "Projects/Alpha/README.md").read_text(encoding="utf-8") == (
            "# Alpha\n\nStatus: Approved\n\nNext: Changed elsewhere.\n"
        ), "Deny should not mutate the target file"
        self.assert_event_contains(
            self.events_since(deny_checkpoint),
            name="edit_proposal_denied",
            expected={
                "vault_name": vault.name,
                "session_id": session_id,
                "artifact_ref": deny_ref,
            },
        )

        denied_proposal = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{deny_ref}"
        ).json()
        denied_apply = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{deny_ref}/apply",
            method="POST",
            data={"selected_edit_ids": [denied_proposal["edits"][0]["edit_id"]]},
        )
        assert denied_apply.status_code == 409, "Denied proposal should not be applicable"
        assert denied_apply.json().get("error") == "ProposalDenied", (
            "Denied proposal apply should use a stable conflict error"
        )

        review_result = create_proposal(
            edits=[
                {
                    "path": "Projects/Alpha/README.md",
                    "original_text": "Status: Approved",
                    "replacement_text": "Status: Final",
                },
                {
                    "path": "Projects/Alpha/README.md",
                    "original_text": "Next: Changed elsewhere.",
                    "replacement_text": "Next: Publish final summary.",
                },
            ],
        )
        review_ref = review_result["artifact_ref"]
        review_proposal = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{review_ref}"
        ).json()
        first_edit = review_proposal["edits"][0]
        second_edit = review_proposal["edits"][1]
        review_response = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{review_ref}/review",
            method="POST",
            data={
                "decisions": [
                    {
                        "edit_id": first_edit["edit_id"],
                        "decision": "approve",
                        "replacement_text": "Status: Final",
                    },
                    {
                        "edit_id": second_edit["edit_id"],
                        "decision": "comment",
                        "comment": "Use a less committal next step.",
                    },
                ],
                "tools": [],
                "model": "test",
            },
        )
        assert review_response.status_code == 200, "Mixed review should start a follow-up chat task"
        review_payload = review_response.json()
        assert first_edit["edit_id"] in review_payload["applied_edit_ids"], (
            "Mixed review should apply approved rows before starting the chat task"
        )
        assert "Already applied edits:" in review_payload["display_prompt"], (
            "Review endpoint should return a concise display prompt"
        )
        assert "Please revise" not in review_payload["display_prompt"], (
            "Agent-facing review instructions should not be exposed as display prompt"
        )
        assert (vault / "Projects/Alpha/README.md").read_text(encoding="utf-8") == (
            "# Alpha\n\nStatus: Final\n\nNext: Changed elsewhere.\n"
        ), "Mixed review should write approved edits and leave commented edits unchanged"

        from core.chat.task_execution import CHAT_TASK_EVENT_BUFFER

        task_id = review_payload.get("task", {}).get("task_id")
        assert task_id, "Mixed review response should include a task id"
        cursor = 0
        for _ in range(1000):
            events = await CHAT_TASK_EVENT_BUFFER.events_after(task_id, cursor)
            for buffered_event in events:
                cursor = buffered_event.sequence
                if buffered_event.is_terminal:
                    assert buffered_event.event == "done", "Mixed review chat task should complete"
                    return
            await asyncio.sleep(0.01)
        raise AssertionError("Mixed review chat task did not complete")
