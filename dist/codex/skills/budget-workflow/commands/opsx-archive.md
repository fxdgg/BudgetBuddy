---
description: Archive a completed change in the experimental workflow
---

Archive a completed change in the experimental workflow.

**Input**: Optionally specify a change name (e.g., `/opsx:archive add-auth`; OpenCode: `/opsx-archive add-auth`). If omitted, check if it can be inferred from conversation context. If vague or ambiguous you MUST prompt for available changes — do NOT guess or auto-select.

**Steps**

1. **Load the openspec-archive-change skill**

   Immediately load the openspec-archive-change skill and follow its process to archive the change. Pass the user's input through:

   > $ARGUMENTS

2. **Follow the skill's guardrails**

   - Always prompt for change selection if not provided
   - Warn on incomplete artifacts or tasks, and confirm before proceeding
   - Assess delta spec sync state before archiving when delta specs exist
   - Run final tests before any branch merge — never merge without green tests

3. **On completion, show summary**

   - Change name, schema used, and archive location
   - Spec sync status (synced / skipped / no delta specs)
   - Note about any warnings (incomplete artifacts or tasks)
