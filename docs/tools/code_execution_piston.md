# `code_execution_piston`

## Purpose

Run code in a remote Piston sandbox when broader language support is needed than the local constrained Python tool provides.

This tool is currently disabled by default.

When enabled, the exposed callable name is `execute_code`.

## Parameters

- `code`: required. Source code to execute.
- `language`: optional. Language name; `language@version` is supported when the runtime exists.
- `stdin`: optional standard input content.

## Output Shape

Returns plain text with compile output, run output, errors, signal, or exit code when present. If the program produces no output and exits cleanly, returns a short success message.

## Notes

- Prefer `code_execution` for ordinary AssistantMD Python tasks.
- Remote runtime availability depends on the configured Piston service.
