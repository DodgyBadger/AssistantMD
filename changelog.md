# Changelog

## 2025-11-11 - Tighten Main Branch Workflow Guardrails

Documented the workflow updates that keep `main` protected while avoiding redundant checks:

- Limited `ci-validation` to pull requests targeting `main` so every change merges only after validation
- Removed the `dev` branch trigger to prevent duplicate runs and simplify branch protection expectations

---

## 2025-11-10 - Streamline Chat UI

Simplified the Chat tab interface for a cleaner, less cluttered experience:

- Removed AssistantMD header to save space
- Replaced status bar with compact icon-based indicator in tab row (✅ when healthy, ⚠️ with message when action needed)
- Made Vault and Model selectors always visible without collapsible wrapper
- Removed redundant labels from selectors (placeholder text is sufficient)
- Renamed "Advanced" section to "Chat Settings"
- Removed History toggle (conversation history now always enabled)
- Removed disabled Compact History button
- Moved New Session button into Chat Settings section alongside Mode selector
- Added warning when no vaults are detected
- Shortened restart warning message for brevity

---
