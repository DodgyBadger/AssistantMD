# `delegate`

## Purpose

Run a focused child agent over a prompt with optional tools, and return its text response.

Use `delegate` when a sub-task needs a model to reason, make decisions, or use tools in a bounded context. The child agent runs in isolation and returns a single response.

## When To Use

- a sub-task needs its own focused prompt and instruction set
- you need bounded tool use that should not share state with the parent agent
- a workflow step produces content that should be summarised, classified, or transformed by a model call
- you want a child agent to read and reason over files using `file_ops_safe`

## When Not To Use

- you only need deterministic file reads, writes, or searches — use `file_ops_safe` directly
- you need to compose structured message history for a follow-up chat turn — use `assemble_context`
- the task is a simple format or transform that plain Python handles without a model call

## Parameters

- `prompt`: required. Primary prompt passed to the child agent. Include file paths here when the child agent should read files.
- `instructions`: optional. System-style instructions layered onto the child agent.
- `model`: optional. Model alias resolved through the shared model configuration. Defaults to the runtime default model when omitted.
- `tools`: optional. List of tool names the child agent may call. `delegate` and `code_execution_local` are always excluded regardless of what is passed. Include `file_ops_safe` when the child agent needs to read files.
- `options`: optional. Less common controls — see Options below.

## Options

Pass as a dictionary to the `options` parameter.

- `thinking`: override thinking for this call. Accepts `true`, `false`, or one of `minimal`, `low`, `medium`, `high`, `xhigh`. When omitted, the current global default thinking policy applies.

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

In scripted Monty flows, `delegate` is a direct tool call that returns a `ScriptToolResult`:

- `output`: the child agent's final text response
- `metadata`: run metadata including `model`, `tool_names`, `thinking`, and `output_chars`
- `items`: empty — delegate does not project source artifacts
- `content`: `None`

```python
result = await delegate(prompt="...", tools=["file_ops_safe"])
summary = result.output
model_used = result.metadata["model"]
```

## Notes

- `delegate` and `code_execution_local` are always removed from the child tool list — recursive delegation is not permitted
- the child agent runs in isolation; its messages do not appear in the parent chat transcript
- to work with files, include the file path in the prompt and add `file_ops_safe` to `tools` — the child agent reads them the same way the parent agent does
- markdown files with embedded local images are handled by `file_ops_safe(read)` inside the child agent, preserving the same multimodal tool-return path used by chat
- when `model` is omitted, the child agent uses the same default model as the runtime
- `options["thinking"]` is separate from the model alias; do not encode thinking level in the model string
