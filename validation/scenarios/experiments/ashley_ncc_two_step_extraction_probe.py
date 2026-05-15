"""
Live-model probe for two-step work extraction from Ashley_NCC chat sessions.

Step 1 reads the full conversation and extracts only summary + user intent.
Step 2 reads that distilled output and extracts classification/search fields.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic import BaseModel, Field

from core.llm.agents import create_agent, generate_response
from core.llm.model_factory import build_model_instance
from core.memory.session_memory import SessionMemoryStore
from core.vector import VectorService
from validation.core.base_scenario import BaseScenario


MODEL_ALIAS = "gpt-mini"
INPUT_PATH = Path("/app/tmp/ashley_ncc_chat_sessions.json")
FIELD_SIMILARITY_FIELDS = ("domain", "work_product", "user_intent", "summary")
FIELD_SIMILARITY_MIN_SCORE = 0.40
FIELD_SIMILARITY_LIMIT = 5
COMPOUND_SIMILARITY_LIMIT = 5
COMPOUND_POLICIES = {
    "score_banded": {
        "description": (
            "Prefer category overlap, then intent support. Treat compound scores "
            ">= 0.7 as automatic recommendations and 0.55-0.7 as possible related work."
        ),
        "weights": {"domain": 0.45, "work_product": 0.35, "user_intent": 0.20, "summary": 0.0},
        "field_min_score": 0.40,
        "min_fields": 1,
        "automatic_threshold": 0.70,
        "possible_threshold": 0.55,
        "rule": "score_band",
    },
    "strict_domain_plus_support": {
        "description": (
            "Require high domain similarity plus high work-product or user-intent "
            "similarity before showing a candidate."
        ),
        "weights": {"domain": 0.45, "work_product": 0.35, "user_intent": 0.20, "summary": 0.0},
        "field_min_score": 0.40,
        "min_fields": 2,
        "automatic_threshold": 0.60,
        "possible_threshold": 0.45,
        "high_domain": 0.65,
        "high_work_product": 0.60,
        "high_user_intent": 0.60,
        "rule": "domain_plus_work_product_or_intent",
    },
}
SESSION_IDS = (
    "Ashley_NCC_20260417_141012",
    "Ashley_NCC_20260417_150221",
    "Ashley_NCC_20260421_115530",
    "Ashley_NCC_20260421_140553",
    "Ashley_NCC_20260425_130302",
    "Ashley_NCC_20260428_152103",
    "Ashley_NCC_20260429_111423",
    "Ashley_NCC_20260429_112347",
    "Ashley_NCC_20260501_140818",
    "Ashley_NCC_20260504_112427",
    "Ashley_NCC_20260504_150832",
    "Ashley_NCC_20260505_143045_834_5l66",
    "Ashley_NCC_20260511_122453_531_mxhe",
    "Ashley_NCC_20260512_094830_603_zu9p",
)


class WorkSummaryIntent(BaseModel):
    """First-pass extraction from the full conversation."""

    summary: str = Field(default="")
    user_intent: str = Field(default="")


class WorkClassification(BaseModel):
    """Second-pass extraction from summary and intent."""

    named_entities: str = Field(default="")
    domain: str = Field(default="")
    work_product: str = Field(default="")


class AshleyNccTwoStepExtractionProbeScenario(BaseScenario):
    """Extract Ashley_NCC work fields using a two-step extraction policy."""

    async def test_scenario(self):
        controller = self._get_system_controller()
        data = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
        sessions_by_id = {session["session_id"]: session for session in data["sessions"]}
        selected_sessions = [sessions_by_id[session_id] for session_id in SESSION_IDS]
        store = SessionMemoryStore(system_root=str(controller._system_root))
        vector_service = VectorService()
        summary_agent = await create_agent(
            model=build_model_instance(MODEL_ALIAS),
            output_type=WorkSummaryIntent,
        )
        classification_agent = await create_agent(
            model=build_model_instance(MODEL_ALIAS),
            output_type=WorkClassification,
        )

        results = []
        for index, session in enumerate(selected_sessions, start=1):
            self._log_timeline(
                "Starting Ashley_NCC two-step extraction "
                f"{index}/{len(selected_sessions)}: {session['session_id']} "
                f"({session['message_count']} messages)"
            )
            first_pass = await generate_response(summary_agent, _build_first_pass_prompt(session))
            summary_intent = first_pass.model_dump()
            second_pass = await generate_response(
                classification_agent,
                _build_second_pass_prompt(session=session, summary_intent=summary_intent),
            )
            classification = second_pass.model_dump()
            extraction = {
                "summary": summary_intent["summary"],
                "user_intent": summary_intent["user_intent"],
                "named_entities": classification["named_entities"],
                "domain": classification["domain"],
                "work_product": classification["work_product"],
            }

            store.upsert_session_memory(
                vault_name=session["vault_name"],
                session_id=session["session_id"],
                title=session["title"],
                summary=extraction["summary"],
                domain=extraction["domain"],
                work_product=extraction["work_product"],
                user_intent=extraction["user_intent"],
                named_entities=extraction["named_entities"],
                metadata={
                    "source": "uploaded_chat_sessions_db",
                    "source_session_id": session["session_id"],
                    "extraction_policy": "two_step_summary_intent_then_classification",
                    "source_created_at": session["created_at"],
                    "source_last_activity_at": session["last_activity_at"],
                    "message_count": session["message_count"],
                    "tool_event_count": session["tool_event_count"],
                },
            )
            indexed_fields = await store.index_session_memory_fields(
                vault_name=session["vault_name"],
                session_id=session["session_id"],
                vector_service=vector_service,
            )
            results.append(
                {
                    "session_id": session["session_id"],
                    "vault_name": session["vault_name"],
                    "title": session["title"],
                    "created_at": session["created_at"],
                    "last_activity_at": session["last_activity_at"],
                    "message_count": session["message_count"],
                    "tool_event_count": session["tool_event_count"],
                    "indexed_fields": indexed_fields,
                    "summary_intent": summary_intent,
                    "classification": classification,
                    "extraction": extraction,
                }
            )
            self._log_timeline(
                "Completed Ashley_NCC two-step extraction "
                f"{session['session_id']}: indexed_fields={indexed_fields}, "
                f"domain={classification['domain']!r}, "
                f"work_product={classification['work_product']!r}"
            )

        artifact = {
            "model": MODEL_ALIAS,
            "input_path": str(INPUT_PATH),
            "memory_db": str(controller._system_root / "memory.db"),
            "vault_name": data["vault_name"],
            "session_count": len(results),
            "session_ids": list(SESSION_IDS),
            "policy": "two_step_summary_intent_then_classification",
            "results": results,
        }
        field_similarity_results = await _run_field_similarity_probes(
            store=store,
            vector_service=vector_service,
            results=results,
            vault_name=data["vault_name"],
        )
        compound_similarity_results = await _run_compound_similarity_probes(
            store=store,
            vector_service=vector_service,
            results=results,
            vault_name=data["vault_name"],
        )
        artifact["field_similarity_results"] = field_similarity_results
        artifact["compound_similarity_results"] = compound_similarity_results
        (self.artifacts_dir / "ashley_ncc_two_step_extractions.json").write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.artifacts_dir / "ashley_ncc_two_step_extractions.md").write_text(
            _render_markdown(artifact),
            encoding="utf-8",
        )
        _write_field_similarity_reports(
            artifacts_dir=self.artifacts_dir,
            field_similarity_results=field_similarity_results,
        )
        _write_compound_similarity_reports(
            artifacts_dir=self.artifacts_dir,
            compound_similarity_results=compound_similarity_results,
        )

        self.soft_assert_equal(
            len(results),
            len(SESSION_IDS),
            "Scenario should extract the selected sessions",
        )
        self.soft_assert(
            all(result["indexed_fields"] > 0 for result in results),
            "Each extracted session memory should index vector-searchable fields",
        )
        self.teardown_scenario()
        self.assert_no_failures()


def _build_first_pass_prompt(session: dict) -> str:
    transcript = "\n\n".join(
        f"{message['role'].upper()} [{message['sequence_index']}]:\n{message['content']}"
        for message in session["messages"]
    )
    title = session.get("title") or ""
    return f"""
Read this AssistantMD chat session and extract only:

- `summary`: a short plain-language summary of the user's work in the session.
- `user_intent`: what the user was trying to accomplish after clarification,
  repetition, or topic drift.

Rules:
- Use only the conversation text and session metadata shown here.
- Focus on the user's real work, not this extraction task.
- Keep both fields concise but specific enough to support later retrieval.
- Return only the structured output.

Session:
- session_id: {session['session_id']}
- vault_name: {session['vault_name']}
- title: {title}
- created_at: {session['created_at']}
- last_activity_at: {session['last_activity_at']}

Conversation:
{transcript}
""".strip()


def _build_second_pass_prompt(*, session: dict, summary_intent: dict) -> str:
    title = session.get("title") or ""
    return f"""
Extract classification fields from this distilled chat-session summary.

Use only the summary, user intent, and session title below. Do not infer from
the original transcript.

Fields:
- `domain`: the subject area or knowledge area of the user's work.
- `work_product`: the real deliverable, answer, document, artifact, or decision
  the user wanted from the session. Use a concise generalized category or short
  noun phrase, not a full sentence. Prefer labels such as `report draft`,
  `funder email`, `briefing note`, `knowledge base`, `source memos`,
  `workflow script`, `project summary`, `grant tracker`, or `decision note`.
- `named_entities`: only named people, organizations, and places. Use a concise
  comma- or semicolon-separated list of entities central to the summarized work.
  Leave empty if there are none.

Rules:
- Keep fields concise but specific enough to support later retrieval.
- For `work_product`, do not use phrases like `memory entry`,
  `memory record`, or `session memory` unless the user's actual task was
  to build memory-system documentation or code.
- Keep `work_product` under 8 words when possible.
- Return only the structured output.

Session:
- session_id: {session['session_id']}
- title: {title}

Summary:
{summary_intent['summary']}

User intent:
{summary_intent['user_intent']}
""".strip()


def _render_markdown(artifact: dict) -> str:
    lines = [
        "# Ashley_NCC Two-Step Work Extraction Probe",
        "",
        f"- model: `{artifact['model']}`",
        f"- vault_name: `{artifact['vault_name']}`",
        f"- session_count: `{artifact['session_count']}`",
        f"- policy: `{artifact['policy']}`",
        f"- memory_db: `{artifact['memory_db']}`",
        "",
    ]
    for result in artifact["results"]:
        extraction = result["extraction"]
        lines.extend(
            [
                f"## {result['session_id']}",
                "",
                f"- title: `{result['title'] or ''}`",
                f"- messages: `{result['message_count']}`",
                f"- tool_events: `{result['tool_event_count']}`",
                f"- indexed_fields: `{result['indexed_fields']}`",
                f"- created_at: `{result['created_at']}`",
                f"- last_activity_at: `{result['last_activity_at']}`",
                "",
                "| Field | Value |",
                "| --- | --- |",
                f"| Domain | {_cell(extraction.get('domain'))} |",
                f"| Work Product | {_cell(extraction.get('work_product'))} |",
                f"| User Intent | {_cell(extraction.get('user_intent'))} |",
                f"| Named Entities | {_cell(extraction.get('named_entities'))} |",
                f"| Summary | {_cell(extraction.get('summary'), limit=1200)} |",
                "",
            ]
        )
    return "\n".join(lines)


async def _run_field_similarity_probes(
    *,
    store: SessionMemoryStore,
    vector_service: VectorService,
    results: list[dict],
    vault_name: str,
) -> list[dict]:
    probes = []
    for field_type in FIELD_SIMILARITY_FIELDS:
        for current in results:
            value = current["extraction"].get(field_type, "").strip()
            matches = ()
            if value:
                matches = await store.search_session_memories_by_field(
                    vault_name=vault_name,
                    field_type=field_type,
                    value=value,
                    vector_service=vector_service,
                    limit=len(results),
                    min_score=FIELD_SIMILARITY_MIN_SCORE,
                )
            other_matches = [
                match.to_dict()
                for match in matches
                if match.session_memory.session_id != current["session_id"]
            ][:FIELD_SIMILARITY_LIMIT]
            probes.append(
                {
                    "session_id": current["session_id"],
                    "query_field": field_type,
                    "query_value": value,
                    "min_score": FIELD_SIMILARITY_MIN_SCORE,
                    "limit": FIELD_SIMILARITY_LIMIT,
                    "current": {
                        "session_id": current["session_id"],
                        "title": current["title"],
                        "extraction": current["extraction"],
                    },
                    "matches": other_matches,
                }
            )
    return probes


async def _run_compound_similarity_probes(
    *,
    store: SessionMemoryStore,
    vector_service: VectorService,
    results: list[dict],
    vault_name: str,
) -> list[dict]:
    probes = []
    for policy_name, policy in COMPOUND_POLICIES.items():
        for current in results:
            candidates: dict[str, dict] = {}
            for field_type, weight in policy["weights"].items():
                if weight <= 0:
                    continue
                value = current["extraction"].get(field_type, "").strip()
                if not value:
                    continue
                matches = await store.search_session_memories_by_field(
                    vault_name=vault_name,
                    field_type=field_type,
                    value=value,
                    vector_service=vector_service,
                    limit=len(results),
                    min_score=policy["field_min_score"],
                )
                for match in matches:
                    session_memory = match.session_memory
                    if session_memory.session_id == current["session_id"]:
                        continue
                    candidate = candidates.setdefault(
                        session_memory.session_id,
                        {
                            "session_memory": match.to_dict()["session_memory"],
                            "score": 0.0,
                            "matched_field_count": 0,
                            "contributions": [],
                        },
                    )
                    field_score = float(match.score)
                    weighted_score = weight * field_score
                    candidate["score"] += weighted_score
                    candidate["matched_field_count"] += 1
                    candidate["contributions"].append(
                        {
                            "field_type": field_type,
                            "match_type": match.match_type,
                            "score": round(field_score, 6),
                            "weight": weight,
                            "weighted_score": round(weighted_score, 6),
                            "matched_value": session_memory.field_value(field_type),
                        }
                    )
            ranked_matches = sorted(
                (
                    candidate
                    for candidate in candidates.values()
                    if _candidate_passes_policy(candidate=candidate, policy=policy)
                ),
                key=lambda candidate: (candidate["score"], candidate["matched_field_count"]),
                reverse=True,
            )[:COMPOUND_SIMILARITY_LIMIT]
            for candidate in ranked_matches:
                candidate["score"] = round(candidate["score"], 6)
                candidate["band"] = _candidate_band(candidate=candidate, policy=policy)
                candidate["contributions"] = sorted(
                    candidate["contributions"],
                    key=lambda contribution: contribution["weighted_score"],
                    reverse=True,
                )
            probes.append(
                {
                    "policy_name": policy_name,
                    "session_id": current["session_id"],
                    "policy": policy,
                    "current": {
                        "session_id": current["session_id"],
                        "title": current["title"],
                        "extraction": current["extraction"],
                    },
                    "matches": ranked_matches,
                }
            )
    return probes


def _candidate_passes_policy(*, candidate: dict, policy: dict) -> bool:
    if candidate["matched_field_count"] < policy["min_fields"]:
        return False
    if policy["rule"] == "score_band":
        return candidate["score"] >= policy["possible_threshold"]
    if policy["rule"] == "domain_plus_work_product_or_intent":
        scores = {
            contribution["field_type"]: contribution["score"]
            for contribution in candidate["contributions"]
        }
        domain_ok = scores.get("domain", 0.0) >= policy["high_domain"]
        work_product_ok = scores.get("work_product", 0.0) >= policy["high_work_product"]
        user_intent_ok = scores.get("user_intent", 0.0) >= policy["high_user_intent"]
        return domain_ok and (work_product_ok or user_intent_ok)
    raise ValueError(f"Unknown compound policy rule: {policy['rule']}")


def _candidate_band(*, candidate: dict, policy: dict) -> str:
    if candidate["score"] >= policy["automatic_threshold"]:
        return "automatic recommendation"
    if candidate["score"] >= policy["possible_threshold"]:
        return "possible related work"
    return "below display threshold"


def _write_field_similarity_reports(
    *,
    artifacts_dir: Path,
    field_similarity_results: list[dict],
) -> None:
    output_dir = artifacts_dir / "field_similarity"
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Field Similarity Reports",
        "",
        f"- fields: `{', '.join(FIELD_SIMILARITY_FIELDS)}`",
        f"- min_score: `{FIELD_SIMILARITY_MIN_SCORE}`",
        "",
        "| Field | Session | Query Value | Matches | Report |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for probe in field_similarity_results:
        field_dir = output_dir / probe["query_field"]
        field_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{_safe_filename(probe['session_id'])}.md"
        (field_dir / filename).write_text(
            _render_field_similarity_report(probe),
            encoding="utf-8",
        )
        lines.append(
            "| "
            f"{_cell(probe['query_field'])} | "
            f"{_cell(probe['session_id'])} | "
            f"{_cell(probe['query_value'])} | "
            f"{len(probe['matches'])} | "
            f"[open](field_similarity/{probe['query_field']}/{filename}) |"
        )
    (artifacts_dir / "field_similarity_index.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _write_compound_similarity_reports(
    *,
    artifacts_dir: Path,
    compound_similarity_results: list[dict],
) -> None:
    output_dir = artifacts_dir / "compound_similarity"
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Compound Similarity Reports",
        "",
        f"- policies: `{', '.join(COMPOUND_POLICIES)}`",
        "",
        "| Policy | Session | Automatic | Possible | Matches | Report |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for probe in compound_similarity_results:
        policy_dir = output_dir / probe["policy_name"]
        policy_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{_safe_filename(probe['session_id'])}.md"
        (policy_dir / filename).write_text(
            _render_compound_similarity_report(probe),
            encoding="utf-8",
        )
        automatic_count = sum(
            1 for match in probe["matches"] if match["band"] == "automatic recommendation"
        )
        possible_count = sum(
            1 for match in probe["matches"] if match["band"] == "possible related work"
        )
        lines.append(
            "| "
            f"{_cell(probe['policy_name'])} | "
            f"{_cell(probe['session_id'])} | "
            f"{automatic_count} | "
            f"{possible_count} | "
            f"{len(probe['matches'])} | "
            f"[open](compound_similarity/{probe['policy_name']}/{filename}) |"
        )
    (artifacts_dir / "compound_similarity_index.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _render_field_similarity_report(probe: dict) -> str:
    current = probe["current"]
    extraction = current["extraction"]
    lines = [
        f"# {probe['query_field']} Similarity: {probe['session_id']}",
        "",
        "## Current Session",
        "",
        f"- session_id: `{current['session_id']}`",
        f"- title: `{current['title'] or ''}`",
        f"- query_value: `{probe['query_value']}`",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Domain | {_cell(extraction.get('domain'))} |",
        f"| Work Product | {_cell(extraction.get('work_product'))} |",
        f"| User Intent | {_cell(extraction.get('user_intent'))} |",
        f"| Summary | {_cell(extraction.get('summary'), limit=1200)} |",
        "",
        "## Matches",
        "",
        "| Rank | Match | Score | Session | Domain | Work Product | User Intent |",
        "| ---: | --- | ---: | --- | --- | --- | --- |",
    ]
    for rank, match in enumerate(probe["matches"], start=1):
        session_memory = match["session_memory"]
        lines.append(
            "| "
            f"{rank} | "
            f"{_cell(match['match_type'])} | "
            f"{_cell(_format_score(match.get('score')))} | "
            f"{_cell(session_memory['session_id'])} | "
            f"{_cell(session_memory.get('domain'))} | "
            f"{_cell(session_memory.get('work_product'))} | "
            f"{_cell(session_memory.get('user_intent'))} |"
        )
    if not probe["matches"]:
        lines.append("|  |  |  |  | No other session memories above threshold |  |  |  |")
    return "\n".join(lines)


def _render_compound_similarity_report(probe: dict) -> str:
    current = probe["current"]
    extraction = current["extraction"]
    lines = [
        f"# Compound Similarity: {probe['policy_name']} / {probe['session_id']}",
        "",
        "## Policy",
        "",
        f"- description: {_cell(probe['policy']['description'], limit=1000)}",
        f"- rule: `{probe['policy']['rule']}`",
        f"- automatic_threshold: `{probe['policy']['automatic_threshold']}`",
        f"- possible_threshold: `{probe['policy']['possible_threshold']}`",
        f"- weights: `{json.dumps(probe['policy']['weights'], sort_keys=True)}`",
        "",
        "## Current Session",
        "",
        f"- session_id: `{current['session_id']}`",
        f"- title: `{current['title'] or ''}`",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Domain | {_cell(extraction.get('domain'))} |",
        f"| Work Product | {_cell(extraction.get('work_product'))} |",
        f"| User Intent | {_cell(extraction.get('user_intent'))} |",
        f"| Summary | {_cell(extraction.get('summary'), limit=1200)} |",
        "",
        "## Ranked Matches",
        "",
        "| Rank | Band | Score | Fields | Session | Domain | Work Product | User Intent |",
        "| ---: | --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for rank, match in enumerate(probe["matches"], start=1):
        session_memory = match["session_memory"]
        lines.append(
            "| "
            f"{rank} | "
            f"{_cell(match['band'])} | "
            f"{_cell(_format_score(match['score']))} | "
            f"{match['matched_field_count']} | "
            f"{_cell(session_memory['session_id'])} | "
            f"{_cell(session_memory.get('domain'))} | "
            f"{_cell(session_memory.get('work_product'))} | "
            f"{_cell(session_memory.get('user_intent'))} |"
        )
    if not probe["matches"]:
        lines.append("|  |  |  | No other session memories above threshold |  |  |  |")
    lines.extend(["", "## Contributions", ""])
    for rank, match in enumerate(probe["matches"], start=1):
        lines.extend(
            [
                f"### {rank}. {match['session_memory']['session_id']}",
                "",
                "| Field | Match | Score | Weight | Weighted | Matched Value |",
                "| --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for contribution in match["contributions"]:
            lines.append(
                "| "
                f"{_cell(contribution['field_type'])} | "
                f"{_cell(contribution['match_type'])} | "
                f"{_cell(_format_score(contribution['score']))} | "
                f"{_cell(_format_score(contribution['weight']))} | "
                f"{_cell(_format_score(contribution['weighted_score']))} | "
                f"{_cell(contribution['matched_value'])} |"
            )
        lines.append("")
    return "\n".join(lines)


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)


def _format_score(value: object) -> str:
    if value is None:
        return ""
    return f"{float(value):.3f}"


def _cell(value: object, *, limit: int = 500) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")[:limit]
