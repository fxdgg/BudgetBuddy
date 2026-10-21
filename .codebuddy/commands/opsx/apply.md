---
name: "Opsx: Apply"
description: Implement tasks from an OpenSpec change (Experimental)
argument-hint: "[command arguments]"
---

Implement tasks from an OpenSpec change.

**Input**: Optionally specify a change name (e.g., `/opsx:apply add-auth`; OpenCode: `/opsx-apply add-auth`). If omitted, check if it can be inferred from conversation context. If vague or ambiguous you MUST prompt for available changes.

**Steps**

1. **Load the openspec-apply-change skill**

   Immediately load the openspec-apply-change skill and follow its process to implement the change. Pass the user's input through:

   > $ARGUMENTS

2. **Follow the skill's guardrails**

   - Read the context files before starting implementation
   - Keep code changes minimal and scoped to each task
   - Update the task checkbox immediately after completing each task
   - Pause on errors, blockers, or unclear requirements — don't guess

3. **On completion or pause, show status**

   - Overall progress: "N/M tasks complete"
   - If all done: suggest archiving via `/opsx:archive`
   - If paused: explain why and wait for guidance
