---
name: parent-delegate
description: Writes a short status report about a project when the user asks for a status report.
---
# Parent report (delegates to a sub-agent)

Follow these steps in order:

1. Write a three-sentence draft about the project the user names.
2. Put the verification code `P-ALPHA-3141` on the first line of your answer.
3. Call the tool `ask_formatter_agent` with the draft as `request`. It returns the report in the final
   house style. Copy its reply into your answer unchanged, below the first line.
