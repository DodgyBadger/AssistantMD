---
schedule: once: 2030-01-01 10:00
workflow_engine: step
enabled: true
description: Development experiment for documentation-driven workflow creation and repair
---

## INSTRUCTIONS
You are a workflow engineer working on AssistantMD. Use primary sources in the documentation to ground every answer. When you reference the docs, cite the relative file path you read so another teammate can reproduce your steps.

General guidance:
- Prefer bullet lists and short sections over long paragraphs.
- When generating workflow files, output clean markdown without code fences.
- Keep file paths relative to the vault root.

## STEP1
@output file:analysis/research
@write-mode append
@header Documentation Recon
@model sonnet
@tools documentation_access

Investigate the AssistantMD documentation to understand how workflows are defined and configured. Create a concise research log that lists the documents you consulted, the most important facts you discovered, and any open questions you want to follow up on.

## STEP2
@output file:outputs/generated_workflow
@write-mode append
@header Proposed Workflow
@model sonnet
@tools documentation_access
@input file:analysis/research

Design a new workflow that helps me plan my day. It should run automatically at 7am, review my goals, and generate a daily plan in the planning folder. Please return a complete workflow file ready to use.

## STEP3
@output file:outputs/fixed_workflow
@write-mode append
@header Repaired Workflow
@model sonnet
@tools documentation_access
@input file:inputs/broken_workflow

You are given a malformed workflow file. Diagnose the issues using documentation references and produce a corrected version that will parse successfully. After the YAML frontmatter, add a short comment section that summarizes the fixes you applied.

## STEP4
@output file:reports/user_summary
@write-mode append
@header User Guidance
@model sonnet
@tools documentation_access
@input file:analysis/research
@input file:outputs/generated_workflow
@input file:outputs/fixed_workflow

Explain to a non-technical teammate what AssistantMD does and how they would work with it day to day. Mention the workflow you created and how it fits into their routine. Keep it approachable and under 250 words.
