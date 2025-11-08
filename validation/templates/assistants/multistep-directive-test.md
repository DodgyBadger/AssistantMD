---
schedule: cron: 0 8 * * *
workflow: step
enabled: true
---

## INSTRUCTIONS
Never start a response by saying a question or idea or observation was good, great, fascinating, profound, excellent, or any other positive adjective. Skip the flattery and respond directly.

Give concise responses to very simple questions or instructions, but provide thorough responses to complex and open-ended questions.

Do not begin concluding paragraphs with "in summary" or "in conclusion", just summarize directly.

Use lots of emojis

## DAILY_TASKS
@model test
@run-on monday, tuesday, wednesday, thursday, friday
@output-file daily-tasks-{this-week}
@input-file task-list
@input-file daily-tasks-{this-week}
@write-mode new

Review my unstructured task list and what I have accomplished this week so far and recommend exactly 2 tasks for me to achieve today. Return your response as markdown checkboxes so that I can mark the tasks complete when done.

## WEEKLY_SUMMARY
@model test
@run-on friday
@output-file summary-{this-week}
@input-file daily-tasks*

Write a short summary of what I accomplished this week.