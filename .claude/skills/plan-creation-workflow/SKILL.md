---
name: plan-creation-workflow
description: For every pending item in needs_action/, reads the task content, categorises it, generates a detailed Plan_XXX.md in plans/ with numbered checkboxes, flags sensitive tasks for human-approval-workflow, and updates the task status to "processing". Always runs after multi-watcher-orchestration and before human-approval-workflow.
---

# Plan Creation Workflow Skill

## Purpose

Every task that enters the pipeline needs a structured plan before any action is taken.
This skill transforms raw task files into actionable plans with checkboxes, assigns categories,
detects sensitivity, and routes accordingly.

**Silver Tier pipeline position:** Step 2 of 6

```
[multi-watcher-orchestration]
        ↓
[plan-creation-workflow]  ← YOU ARE HERE
        ↓
[human-approval-workflow]  (sensitive tasks)
[mcp-action-handler]       (non-sensitive tasks that need tools)
[dashboard-updater]        (all tasks)
```

---

## Instructions

### Step 1 — Find pending tasks

Scan `needs_action/` for all `.meta.json` files where `"status": "pending"`.
For each, load the companion task file.

**Script reference:** `skills/task_analyzer.py` → `find_pending_tasks()`

### Step 2 — Analyse content

For each task file, extract:

| Field | Method |
|-------|--------|
| `word_count` | `len(text.split())` |
| `line_count` | `len(text.splitlines())` |
| `char_count` | `len(text.strip())` |
| `key_phrases` | First 5 non-empty lines |
| `category` | Keyword matching (see table below) |
| `source` | From `.meta.json` (`inbox`, `email`, `linkedin`, `whatsapp`) |
| `sensitive` | Sensitivity check (see below) |

**Category keyword table:**

| Category | Trigger keywords |
|----------|-----------------|
| `bug/fix` | bug, fix, error, issue, broken, crash |
| `feature` | feature, add, implement, create, build, new |
| `documentation` | doc, readme, write up, summary, notes |
| `research` | research, investigate, explore, analyze, study |
| `urgent` | urgent, asap, critical, immediately, deadline |
| `education` | curriculum, lesson, teach, learn, course, study plan |
| `linkedin-post` | post, linkedin, share, publish, announce |
| `email-reply` | reply, respond, email, message, re: |
| `general` | (default — no keyword matched) |

**Script reference:** `skills/task_analyzer.py` → `analyze_content()` + `_categorize()`

### Step 3 — Sensitivity check

A task is **sensitive** if ANY of the following are true:
- `category` is `linkedin-post`, `email-reply`, or `payment`
- `source` is `linkedin` or `email` (external communication always needs review)
- Task text contains: `send`, `post`, `publish`, `pay`, `transfer`, `invoice`, `reply`, `respond`
- Task text contains any monetary value pattern: `$`, `£`, `€`, `USD`, `GBP`

Flag sensitive tasks with `"sensitive": true` in the meta.

### Step 4 — Generate Plan_XXX.md

Create `plans/Plan_<task-slug>.md` using this exact template:

```markdown
# Plan: <task-name>

**Category:** <category>
**Source:** <source>
**Sensitive:** <Yes ⚠️ | No ✅>
**Generated:** <ISO-8601-UTC>
**Cycle:** Silver

---

## Summary
<1–2 sentence description of what this task requires>

## Checklist

- [ ] Read and confirm task content understood
- [ ] Categorise as: <category>
- [ ] Sensitivity check: <result>
- [ ] <Action step specific to this category — e.g. "Draft email reply" or "Generate curriculum">
- [ ] <Second action step>
- [ ] <Third action step>
- [ ] Route to human-approval-workflow (if sensitive)
- [ ] Execute via mcp-action-handler (if approved and needs MCP)
- [ ] Update dashboard via dashboard-updater
- [ ] Move task file to done/

## Key Information Extracted
<key_phrases as bullet list>

## Original Content
\`\`\`
<raw task file content>
\`\`\`

## Agent Notes
<!-- AI fills this in during execution -->
```

Checklist items must be **specific to the task category**:

| Category | Required checklist items |
|----------|------------------------|
| `education` | Draft structured curriculum, include module breakdown, add assessment milestones |
| `linkedin-post` | Read Business_Goals.md, draft post, route to human-approval-workflow |
| `email-reply` | Extract sender/subject, draft reply, route to human-approval-workflow |
| `bug/fix` | Reproduce issue, identify root cause, propose fix |
| `feature` | Define requirements, outline implementation steps, list affected files |
| `research` | Define research question, list sources, summarise findings |
| `urgent` | Flag as priority, assess deadline, escalate if needed |

**Script reference:** `agents/task_agent.py` → `generate_plan()`

### Step 5 — Update meta status

Update `needs_action/<filename>.meta.json`:
```json
{
  "status": "processing",
  "analyzed_at": "<ISO-8601-UTC>",
  "sensitive": <true|false>,
  "category": "<category>",
  "plan": "plans/Plan_<task-slug>.md",
  "analysis": { ... }
}
```

**Script reference:** `skills/task_analyzer.py` → `update_meta_status()`

### Step 6 — Append to logs/summary.md

```markdown
## <task-name> — <ISO-8601-UTC>
- Status: processing
- Category: <category>
- Sensitive: <yes/no>
- Plan: plans/Plan_<task-slug>.md
- Words: <N> | Lines: <N>
- Key phrases: ...

---
```

**Script reference:** `skills/task_analyzer.py` → `append_summary()`

### Step 7 — Route

- **Sensitive tasks** → hand off to `human-approval-workflow`
- **Non-sensitive tasks** → hand off to `mcp-action-handler` (if tools needed) or complete directly
- **All tasks** → call `dashboard-updater` to reflect new "processing" status

---

## Output Contract

After this skill runs, every processed task must have:
1. A plan file at `plans/Plan_<task-slug>.md` with all checkboxes unchecked
2. A `.meta.json` with `"status": "processing"` and `"plan"` key set
3. A `logs/summary.md` entry
4. A routing decision logged in the plan's "Agent Notes" section

---

## References

- `skills/task_analyzer.py` — Bronze-tier analyzer (extend, don't replace)
- `agents/task_agent.py` — `generate_plan()` template logic
- `README.md` — "Step 2: Analyzer" and "Step 3: Agent"
- `CLAUDE.md` — "Key Conventions" and "Status flow"
- `company_handbook.md` — Rules that may override default routing
