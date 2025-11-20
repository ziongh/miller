---
allowed-tools: recall
argument-hint: [time|topic] [--type type] [--since time]
description: Retrieve development memories (user)
---

IMMEDIATELY retrieve development memories based on the provided query. DO NOT wait or ask for confirmation.

Determine query mode from $ARGUMENTS and execute the appropriate tool NOW:

**Time-based query** (e.g., "30m", "1hr", "3d"):
⚠️ CRITICAL: Get actual current time from system BEFORE calculations!

1. Run `date '+%Y-%m-%dT%H:%M:%S'` to get current LOCAL datetime
   Example output: "2025-11-14T20:53:43"
2. Parse the time expression (m/min=minutes, h/hr=hours, d/day=days)
3. Add 10-minute margin for reliability (e.g., "10m" → look back 20 minutes)
   - Accounts for: time calculation edge cases, user imprecision
4. Calculate the "since" datetime by subtracting (duration + margin) from current time
   - Use LOCAL time format (NO 'Z' suffix) - tool converts to UTC automatically
   - Format: "YYYY-MM-DDTHH:MM:SS" (example: "2025-11-14T20:33:43")
5. IMMEDIATELY call recall tool with the since parameter

💡 TIP: For very recent memories (< 30 minutes), just use limit instead:
   "/recall" (no args) → last 10 memories

**Topic-based query** (e.g., "startup indexing", "authentication bug", "PostgreSQL decision"):
1. IMMEDIATELY call recall tool with:
   - query=$ARGUMENTS (enables semantic search using indexed embeddings)
   - limit=20 (get more results for topic searches)

💡 NEW: Semantic search uses Miller's hybrid text+semantic engine for intelligent topic matching!

**Filtered query** (e.g., "--type decision", "--since 2d"):
1. Parse the flags (--type, --since)
2. IMMEDIATELY call recall tool with the appropriate filters
3. Can combine with query for semantic + filter combinations

**Combined query** (e.g., "authentication --type decision --since 2d"):
1. Parse flags from $ARGUMENTS
2. Extract remaining text as query
3. IMMEDIATELY call recall with both query and filters
   Example: recall(query="authentication", type="decision", since="2025-11-17")

**No arguments provided**:
1. IMMEDIATELY call recall tool with limit=10 to get the last 10 memories

After retrieving results, present them formatted with:
- Type icon (✓ checkpoint, 🎯 decision, 💡 learning, 👁️ observation)
- Description
- Relative time and git branch
- Tags (if present)
- Keep output scannable (newest first)
