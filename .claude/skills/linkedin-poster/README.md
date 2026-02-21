# LinkedIn Poster Skill

**Path:** `.claude/skills/linkedin-poster/`
**Type:** Agent Skill (human-in-the-loop)
**Sensitivity:** External write — always routed through `Pending_Approval/`

---

## What it does

1. Reads `Business_Goals.md` for company/personal context
2. Reads the 3 most recent `plans/Plan_*.md` files for topic inspiration
3. Generates a professional LinkedIn post draft
4. Writes an approval request to `Pending_Approval/`
5. When you move the file to `Approved/`, posts it to LinkedIn via Playwright
6. Logs result to `dashboard.md` and `system_logs.md`

---

## Approval Flow

```
Pending_Approval/
  linkedin_post_<slug>_<timestamp>.approval.md   ← edit post here if needed
  linkedin_post_<slug>_<timestamp>.approval.md.meta.json

      ↓ move to Approved/ (or Rejected/)

Approved/
  linkedin_post_<slug>_<timestamp>.approval.md   ← triggers posting

      ↓ run post_approved

Done/
  linkedin_post_<slug>_<timestamp>.approval.md   ← archived with posted_at
```

---

## Usage

### From Python
```python
from .claude.skills.linkedin-poster import run

run()                          # auto-generate from goals + plans
run(topic="AI automation")     # specific topic
run(post_approved=True)        # post all items in Approved/
```

### From CLI
```bash
# Generate a draft
python -m .claude.skills.linkedin-poster

# Generate on a specific topic
python .claude/skills/linkedin-poster/linkedin_poster.py "hackathon lessons"

# Post approved items
python .claude/skills/linkedin-poster/linkedin_poster.py post_approved
```

### From Claude Code (invoke as skill)
```
/linkedin-poster
/linkedin-poster topic="AI automation wins"
/linkedin-poster post_approved
```

---

## Prerequisites

```bash
pip install playwright
python -m playwright install chromium
python linkedin_watcher.py --login   # save LinkedIn session once
```

Create `Business_Goals.md` in the vault root to customise post context:
```markdown
# Business Goals
- Build AI automation tools for knowledge workers
- Share learnings on LinkedIn weekly
- Grow professional network in AI/ML space
```

---

## Files touched

| File | Action |
|------|--------|
| `Business_Goals.md` | Read (context) |
| `plans/Plan_*.md` | Read (topic inspiration) |
| `Pending_Approval/<name>.approval.md` | Written (approval request) |
| `Approved/<name>.approval.md` | Read (trigger posting) |
| `done/<name>.approval.md` | Written (archived after posting) |
| `dashboard.md` | Updated (Recent LinkedIn Posts table) |
| `system_logs.md` | Updated (activity log) |

---

## Security notes

- Posts are **never sent without explicit human approval** — approval files must be manually moved to `Approved/`
- Sensitive content (prices, confidential info, political topics) is flagged in the approval file
- Playwright uses the same persistent session as `linkedin_watcher.py` — no credentials stored in code
