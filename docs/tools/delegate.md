# `delegate`

## Purpose

Run a focused child agent over a prompt with optional tools, and return its text response.

## When To Use

- an authoring script needs model inference for summarising, classifying, drafting, or deciding from prepared inputs
- the user explicitly asks the chat agent to delegate a focused sub-task
- the chat agent has a clearly separable sub-task that benefits from an isolated prompt and tool set
- the chat agent needs to explore a large set of vault files or run many web searches / extractions where cumulative tool output could crowd the parent context

Use `delegate` for efficient delegation, not as a larger context bucket. Before using `delegate` in chat, briefly tell the user the delegation strategy and wait for confirmation. If one deterministic tool call can answer, use that directly. For large vault or web exploration, split work into bounded subtasks and make multiple delegate calls if needed. Each child should inspect a scoped path, query, source group, or hypothesis and return a compact summary, decision, or saved artifact path. Prefer instructions such as "inspect these likely paths first", "sample this directory and report whether deeper inventory is needed", or "write the full report to `Reports/...` and return only counts and the saved path" over instructions that require one child to enumerate and reason over an entire vault in one pass.

## Arguments

- `prompt`: required. Primary prompt passed to the child agent. Include file paths here when the child agent should read files.
- `instructions`: optional. System-style instructions layered onto the child agent.
- `model`: optional. Model alias resolved through the shared model configuration. Defaults to the runtime default model when omitted.
- `tools`: optional. List of tool names the child agent may call. `delegate` and `code_execution` are always excluded regardless of what is passed. Include `file_ops_safe` when the child agent needs to read files.
- `options`: optional dictionary. Supported key: `thinking`, which accepts `true`, `false`, or one of `minimal`, `low`, `medium`, `high`, `xhigh`.

## Examples

```python
result = await delegate(
    prompt="Summarise the note at notes/seed.md in two sentences.",
    tools=["file_ops_safe"],
    model="flash",
)
```

```python
result = await delegate(
    prompt="Identify the main trend shown in the chart at images/chart.png.",
    tools=["file_ops_safe"],
    model="flash",
)
```

```python
result = await delegate(
    prompt="Find the most recent invoice in Finance/Invoices and return the total.",
    tools=["file_ops_safe"],
    instructions="Return only the numeric total.",
)
```

```python
result = await delegate(
    prompt="Classify this support ticket as urgent, normal, or low priority:\n\n" + ticket_text,
    instructions="Return only the priority label.",
    options={"thinking": False},
)
```

## Output Shape

Returns the child agent's final text response.

In scripted Monty flows, direct calls return an object with `output`, `metadata`, `content`, and `items`:

- `output`: child agent final text response
- `metadata`: run metadata including `model`, `tool_names`, `thinking`, and `output_chars`
- `content`: `None`
- `items`: empty; `delegate` does not project source artifacts

```python
result = await delegate(prompt="...", tools=["file_ops_safe"])
summary = result.output
model_used = result.metadata["model"]
```

## Notes

- `delegate` and `code_execution` are always removed from the child tool list — recursive delegation is not permitted
- the child agent runs in isolation; its messages do not appear in the parent chat transcript
- child runs are bounded; if the child exceeds its tool-call or timeout guardrail, `delegate` returns a failed tool result with guidance instead of crashing the parent run
- to work with files, include the file path in the prompt and add `file_ops_safe` to `tools` — the child agent reads them the same way the parent agent does
- markdown files with embedded local images are handled by `file_ops_safe(read)` inside the child agent, preserving the same multimodal tool-return path used by chat
- when `model` is omitted, the child agent uses the same default model as the runtime
- `options["thinking"]` is separate from the model alias; do not encode thinking level in the model string
