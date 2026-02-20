---
passthrough_runs: all
description: Pass summary of available skills to the chat agent.
---

## Chat Instructions
The following skills are available to help you fulfill the user's request. Select what seems most appropriate and then read the full skill at the path provided.

## Skills
@input file: AssistantMD/Skills/* (output=context, properties="name,description")  
@model none

