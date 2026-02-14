---
token_threshold: 25000
passthrough_runs: 3
description: Regular chat with a lightweight compact step when history gets long.
---

## Chat Instructions
Stay concise, practical, and focused on the user's goals.

## Context Instructions
Summarize the conversation using the template below.

Rules:
- Follow the template exactly.
- Use only the provided history; do not invent details.
- If a field is not applicable, output "N/A".

## Compact Summary
@recent_runs all
@model gpt-mini

Summarize the conversation so the chat agent can continue smoothly.

Template:
- mission:
- constraints:
- key_points:
- decisions:
- next_steps:
- recent_turns:
- latest_input:
- chat_agent_instructions:
