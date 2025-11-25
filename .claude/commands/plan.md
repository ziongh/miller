---
allowed-tools: plan
argument-hint: [title|list|done|"plan_id"]
description: Manage development plans (user)
---

Manage development plans using Miller's memory system. Plans track complex multi-step work.

**Parse $ARGUMENTS to determine action:**

**No arguments or "list"**:
1. Call plan(action="list") to show all plans
2. Highlight the active plan (if any) with progress

**"done" or "complete"**:
1. Call plan(action="list", status="active") to find active plan
2. If found, call plan(action="complete", id=<active_plan_id>)
3. Confirm: "🎉 Completed '<title>'!"
4. If no active plan, say "No active plan to complete"

**A plan ID (starts with "plan_")**:
1. Call plan(action="get", id=$ARGUMENTS) to show that plan's details

**Any other text (treated as new plan title)**:
1. Call plan(action="save", title=$ARGUMENTS)
2. Confirm: "📋 Created plan '<title>' - now active"
3. Suggest: "Use /plan done when finished, or /plan to see all plans"

**Examples:**
- `/plan` → list all plans with status
- `/plan Add user authentication` → create new plan with that title
- `/plan done` → complete the active plan
- `/plan plan_add-user-auth` → show details of specific plan

**Status icons:**
- ● active (currently working on)
- ○ pending (paused/queued)
- ✓ completed (done)
