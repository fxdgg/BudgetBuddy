---
name: "Opsx: Explore"
description: Enter explore mode - think through ideas, investigate problems, clarify requirements
argument-hint: "[command arguments]"
---

Enter explore mode. Think deeply. Visualize freely. Follow the conversation wherever it goes.

**Input**: The argument is whatever the user wants to think about — a vague idea, a specific problem, a change name, a comparison, or nothing (just enter explore mode).

**Steps**

1. **Load the openspec-explore skill**

   Immediately load the openspec-explore skill and adopt its exploration stance. Pass the user's input through:

   > $ARGUMENTS

2. **Key constraint: explore mode is for thinking, not implementing**

   You may read files, search code, and investigate the codebase, but you must NEVER write code or implement features. If the user asks you to implement something, remind them to exit explore mode first and create a change proposal (e.g., via `/opsx:propose`). Creating OpenSpec artifacts is fine — that's capturing thinking, not implementing.
