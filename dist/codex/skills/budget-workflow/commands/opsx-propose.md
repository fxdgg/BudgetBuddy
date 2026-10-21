---
description: Propose a new change - create it and generate all artifacts in one step
---

Propose a new change - create the change and generate all artifacts in one step.

I'll create a change with artifacts:
- proposal.md (what & why)
- design.md (how)
- tasks.md (implementation steps)

When ready to implement, run `/opsx:apply` (OpenCode: `/opsx-apply`).

**Input**: The argument is the change name (kebab-case), OR a description of what the user wants to build. If no input is provided, ask what they want to build — do NOT proceed without understanding what the user wants.

**Steps**

1. **Load the openspec-propose skill**

   Immediately load the openspec-propose skill and follow its process to create the change and generate all artifacts. Pass the user's input through:

   > $ARGUMENTS

2. **Follow the skill's guardrails**

   - Create ALL artifacts needed for implementation (as defined by the schema's apply requirements)
   - Always read dependency artifacts before creating a new one
   - Verify each artifact file exists after writing before proceeding to the next
   - If context is critically unclear, ask the user — but prefer reasonable decisions to keep momentum

3. **On completion, show final status**

   - Change name and location
   - List of artifacts created with brief descriptions
   - Prompt: "Run `/opsx:apply` to start implementing."
