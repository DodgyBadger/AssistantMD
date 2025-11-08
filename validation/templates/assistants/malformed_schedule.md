---
schedule: every 1d at 9am
workflow: step
enabled: true
description: Malformed assistant with invalid old schedule syntax
---

## STEP1
@output-file test.md

This assistant has invalid schedule syntax (old format) and should fail to load without crashing the system.
