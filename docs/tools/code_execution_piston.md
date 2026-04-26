# `execute_code`

## Purpose

Run code in a remote Piston sandbox when broader language support is needed than the local constrained Python tool provides.

This tool is currently disabled by default.

## Parameters

- `code`: required. Source code to execute.
- `language`: optional. Language name; `language@version` is supported when the runtime exists.
- `stdin`: optional standard input content.

## Notes

- Prefer `code_execution_local` for ordinary AssistantMD Python tasks.
- Remote runtime availability depends on the configured Piston service.
