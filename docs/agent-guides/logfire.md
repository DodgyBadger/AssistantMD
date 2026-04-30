# Logfire

Use Logfire when runtime traces can answer a question faster than reproducing the issue locally.

## Query Basics

- Call `query_schema_reference` before `query_run`.
- Always constrain by time range and add `LIMIT`.
- Prefer selecting specific columns over `SELECT *`, especially when traces may contain image or file payloads.
- Use the project name returned by the MCP server. In this environment, the query project may be `ai-assistant` even when dashboard URLs include the organization path.

## Pydantic AI Filter

Use this filter to cut out most non-agent framework noise in both the dashboard and MCP queries:

```sql
SELECT *
FROM records
WHERE otel_scope_name = 'pydantic-ai'
```

For MCP use, keep the same filter but narrow the time range and selected columns:

```sql
SELECT start_timestamp, trace_id, span_id, parent_span_id, span_name, message
FROM records
WHERE start_timestamp >= TIMESTAMP '2026-04-26T20:00:00Z'
  AND start_timestamp < TIMESTAMP '2026-04-26T20:20:00Z'
  AND otel_scope_name = 'pydantic-ai'
ORDER BY start_timestamp ASC
LIMIT 200
```

## Useful Patterns

Find delegate lifecycle events:

```sql
SELECT start_timestamp, trace_id, level, message, attributes->'data' AS data
FROM records
WHERE start_timestamp >= TIMESTAMP '2026-04-26T20:00:00Z'
  AND start_timestamp < TIMESTAMP '2026-04-26T20:20:00Z'
  AND message IN (
    'delegate_started',
    'delegate_completed',
    'delegate_failed',
    'delegate_tool_binding_resolved'
  )
ORDER BY start_timestamp ASC
LIMIT 100
```

Inspect child-agent tool choices without pulling full payloads:

```sql
SELECT start_timestamp, span_id, parent_span_id, span_name, message,
       attributes->'input_data'->>'name' AS input_name,
       attributes->'input_data'->>'arguments' AS input_args,
       attributes->'result'->>'name' AS result_name,
       attributes->'result'->>'arguments' AS result_args
FROM records
WHERE trace_id = 'TRACE_ID_HERE'
  AND (
    span_name LIKE 'running tool:%'
    OR attributes->'input_data'->>'name' IN ('delegate', 'file_ops_safe')
    OR attributes->'result'->>'name' IN ('delegate', 'file_ops_safe')
  )
ORDER BY start_timestamp ASC
LIMIT 200
```

Read model outputs for selected spans:

```sql
SELECT start_timestamp, span_id, attributes->'gen_ai.output.messages' AS output_messages
FROM records
WHERE trace_id = 'TRACE_ID_HERE'
  AND span_id IN ('SPAN_ID_HERE')
ORDER BY start_timestamp ASC
LIMIT 20
```

## Payload Hygiene

- Avoid selecting full `attributes` on multimodal traces; image bytes or large tool results can dominate the response.
- Prefer JSON subfields such as `attributes->'data'`, `attributes->'input_data'->>'arguments'`, and `attributes->'gen_ai.output.messages'`.
- If a query is truncated, narrow by `trace_id`, `span_id`, `message`, or `span_name` before increasing `LIMIT`.

## Trace Links

Use `project_logfire_link` with the trace id to produce a dashboard URL after identifying the relevant trace.
