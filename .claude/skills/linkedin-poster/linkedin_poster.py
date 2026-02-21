"""
linkedin_poster.py — LinkedIn Post Generator Skill

Workflow:
  1. Read Business_Goals.md for company/personal context
  2. Read recent plans from plans/Plan_*.md (last N)
  3. Generate a professional LinkedIn post draft
  4. Classify post complexity → if simple, create approval file
  5. When approved (file moved to Approved/), post via Playwright
  6. Log result to dashboard.md and system_logs.md

Usage:
  from .linkedin_poster import run
  run()                        # auto-generate from goals + plans
  run(topic="AI automation")   # generate on a specific topic
  run(post_approved=True)      # scan Approved/ and post waiting items
"""

import json
import re
import shutil
import textwrap
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────
SKILL_DIR        = Path(__file__).parent
VAULT_DIR        = SKILL_DIR.parent.parent.parent   # .claude/skills/linkedin-poster → vault root
PLANS_DIR        = VAULT_DIR / "plans"
DONE_DIR         = VAULT_DIR / "done"
PENDING_DIR      = VAULT_DIR / "Pending_Approval"
APPROVED_DIR     = VAULT_DIR / "Approved"
REJECTED_DIR     = VAULT_DIR / "Rejected"
DASHBOARD_FILE   = VAULT_DIR / "dashboard.md"
SYSTEM_LOGS_FILE = VAULT_DIR / "system_logs.md"
GOALS_FILE       = VAULT_DIR / "Business_Goals.md"
SESSION_DIR      = VAULT_DIR / ".linkedin_session"

# ── Sensitivity classifier ───────────────────────────────────────────────────
SENSITIVE_PATTERNS = [
    r"\bcontroversi", r"\bpolitics?\b", r"\breligion\b", r"\blatest deal\b",
    r"\bprice\b", r"\bsalary\b", r"\bconfidential\b", r"\binternal\b",
    r"\bexclusive offer\b", r"\bdiscount\b", r"\bpromotion\b",
]


def _is_sensitive(text: str) -> bool:
    """Return True if the post content triggers any sensitivity flag."""
    lower = text.lower()
    return any(re.search(pat, lower) for pat in SENSITIVE_PATTERNS)


# ── Context readers ──────────────────────────────────────────────────────────
def read_business_goals() -> str:
    """Read Business_Goals.md. Returns content string or a default stub."""
    if GOALS_FILE.exists():
        content = GOALS_FILE.read_text(encoding="utf-8").strip()
        return content if content else _default_goals()
    return _default_goals()


def _default_goals() -> str:
    return (
        "Goals: build an autonomous AI employee pipeline; demonstrate value of "
        "file-based task automation; share learnings on AI productivity and "
        "hackathon development."
    )


def read_recent_plans(n: int = 3) -> list[dict]:
    """
    Return the N most recently modified Plan_*.md files as dicts with
    keys: name, title, content (first 400 chars).
    """
    plan_files = sorted(
        PLANS_DIR.glob("Plan_*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:n]

    plans = []
    for pf in plan_files:
        text = pf.read_text(encoding="utf-8")
        # Extract title from first heading
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = title_match.group(1) if title_match else pf.stem
        plans.append({
            "name": pf.name,
            "title": title,
            "snippet": text[:400].strip(),
        })
    return plans


# ── Post generator ───────────────────────────────────────────────────────────
def generate_post(topic: str | None, goals: str, plans: list[dict]) -> dict:
    """
    Build a professional LinkedIn post draft.

    Returns a dict:
      post_text   — the ready-to-post string
      title       — short slug for filenames
      hook        — first line
      sensitive   — bool
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%B %d, %Y")

    # Derive the subject from topic or from most recent plan
    if topic:
        subject = topic.strip()
    elif plans:
        subject = plans[0]["title"].replace("Plan: ", "").strip()
    else:
        subject = "AI-Powered Task Automation"

    # Build bullet insights from plan snippets — find actual prose sentences
    insights = []
    skip_patterns = re.compile(
        r"(^\||Plan:|Category:|Sensitivity:|Generated:|Word count:"
        r"|Source|Action Items|```|---|Request Summary|Checklist"
        r"|bytes|status|words|lines)"
    )
    for p in plans[:3]:
        for line in p["snippet"].splitlines():
            clean = re.sub(r"\*+", "", line).strip().lstrip("#-|> ").strip()
            if (len(clean) > 30
                    and not skip_patterns.search(clean)
                    and clean[0].isalpha()
                    and " " in clean):
                insights.append(clean[:110])
                break

    if insights:
        bullets = "\n".join(f"* {i}" for i in insights)
    else:
        bullets = (
            "* Automated file-to-task pipeline running end-to-end\n"
            "* Plans generated per task with full audit trail\n"
            "* Human-in-the-loop approval for every sensitive action"
        )

    # Extract a meaningful goal line (skip headings)
    goal_snippet = ""
    for line in goals.splitlines():
        clean = line.strip().lstrip("#- ").strip()
        if len(clean) > 20 and not clean.startswith("*"):
            goal_snippet = clean[:150]
            break

    post_text = "\n".join([
        "Building the future of work, one automated task at a time.",
        "",
        f"Over the past sprint I have been developing an AI Employee Vault: a fully autonomous,",
        f"file-based pipeline where tasks dropped into an inbox are analyzed, planned, executed,",
        f"and logged with no manual intervention required.",
        "",
        f"Here is what we shipped around '{subject}':",
        "",
        bullets,
        "",
        "The key insight? Giving AI a structured environment (clear folders, metadata, approval",
        "gates) unlocks reliability that ad-hoc prompting never could.",
        "",
        "What I am learning:",
        "- Human-in-the-loop approval keeps AI actions trustworthy",
        "- File-based pipelines are surprisingly robust and auditable",
        "- Small, composable skills beat monolithic agents",
        "",
        goal_snippet,
        "",
        "Would love to hear how others are approaching autonomous AI workflows. Drop a comment.",
        "",
        "#AIAutomation #ProductivityTools #MachineLearning #BuildingInPublic #Hackathon",
    ])

    # Sensitivity check
    sensitive = _is_sensitive(post_text)

    # Short slug for filenames
    slug = re.sub(r"[^\w]", "_", subject.lower())[:40]
    title = f"linkedin_post_{slug}_{now.strftime('%Y%m%d_%H%M%S')}"

    return {
        "post_text": post_text,
        "title": title,
        "hook": post_text.splitlines()[0],
        "subject": subject,
        "sensitive": sensitive,
        "generated_at": now.isoformat(),
    }


# ── Approval file writer ─────────────────────────────────────────────────────
def create_approval_file(post: dict) -> Path:
    """
    Write an approval request to Pending_Approval/.
    Returns the path to the approval file.
    """
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"{post['title']}.approval.md"
    approval_path = PENDING_DIR / filename

    content = (
        f"# LinkedIn Post — Pending Approval\n\n"
        f"**Title:** {post['subject']}\n"
        f"**Generated:** {post['generated_at']}\n"
        f"**Sensitive:** {'Yes ⚠️' if post['sensitive'] else 'No ✅'}\n"
        f"**Skill:** linkedin-poster\n\n"
        f"---\n\n"
        f"## Post Content\n\n"
        f"{post['post_text']}\n\n"
        f"---\n\n"
        f"## Instructions\n\n"
        f"- **To approve:** Move this file to `Approved/`\n"
        f"- **To reject:** Move this file to `Rejected/`\n"
        f"- **To edit:** Modify the post content above, then move to `Approved/`\n\n"
        f"Once approved, run:\n"
        f"```\npython -m .claude.skills.linkedin-poster post_approved\n```\n"
        f"or trigger via the pipeline to auto-post.\n"
    )

    approval_path.write_text(content, encoding="utf-8")

    # Write companion meta
    meta = {
        "name": filename,
        "title": post["subject"],
        "generated_at": post["generated_at"],
        "sensitive": post["sensitive"],
        "status": "pending_approval",
        "type": "linkedin_post",
    }
    meta_path = Path(str(approval_path) + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return approval_path


# ── LinkedIn poster (Playwright) ─────────────────────────────────────────────
def post_to_linkedin(post_text: str) -> bool:
    """
    Post text to LinkedIn using the persistent Playwright session.
    Returns True on success, False on failure.

    Requires:
        pip install playwright
        python -m playwright install chromium
        python linkedin_watcher.py --login   (to save session)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[linkedin-poster] [!] playwright not installed. Run: pip install playwright")
        return False

    if not SESSION_DIR.exists():
        print(
            "[linkedin-poster] [!] No LinkedIn session found. "
            "Run: python linkedin_watcher.py --login"
        )
        return False

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                str(SESSION_DIR), headless=True
            )
            page = browser.pages[0] if browser.pages else browser.new_page()

            # Navigate to LinkedIn feed
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # Click the "Start a post" button
            start_post_selectors = [
                "[data-control-name='share.sharebox_text']",
                ".share-box-feed-entry__trigger",
                "button[aria-label='Start a post']",
                ".share-creation-state__placeholder",
            ]
            clicked = False
            for sel in start_post_selectors:
                try:
                    page.click(sel, timeout=5000)
                    clicked = True
                    break
                except Exception:
                    continue

            if not clicked:
                print("[linkedin-poster] [x]Could not find 'Start a post' button.")
                browser.close()
                return False

            page.wait_for_timeout(2000)

            # Type the post content
            editor_selectors = [
                ".ql-editor",
                "[role='textbox']",
                ".share-creation-state__editor",
            ]
            typed = False
            for sel in editor_selectors:
                try:
                    page.fill(sel, post_text, timeout=5000)
                    typed = True
                    break
                except Exception:
                    continue

            if not typed:
                print("[linkedin-poster] [x]Could not find post editor.")
                browser.close()
                return False

            page.wait_for_timeout(1500)

            # Click "Post" button
            post_btn_selectors = [
                "button[data-control-name='share.post']",
                ".share-actions__primary-action",
                "button.share-box_actions",
            ]
            posted = False
            for sel in post_btn_selectors:
                try:
                    page.click(sel, timeout=5000)
                    posted = True
                    break
                except Exception:
                    continue

            browser.close()

            if posted:
                print("[linkedin-poster] Post published to LinkedIn.")
            else:
                print("[linkedin-poster] Could not click the Post button.")
            return posted

    except Exception as e:
        print(f"[linkedin-poster] [x]Error during posting: {e}")
        return False


# ── Process approved posts ────────────────────────────────────────────────────
def process_approved() -> int:
    """
    Scan Approved/ for linkedin_post_*.approval.md files.
    For each: extract post text, post to LinkedIn, move to done/, log.
    Returns count of posts published.
    """
    APPROVED_DIR.mkdir(parents=True, exist_ok=True)
    DONE_DIR.mkdir(parents=True, exist_ok=True)

    approved_files = list(APPROVED_DIR.glob("linkedin_post_*.approval.md"))
    if not approved_files:
        print("[linkedin-poster] No approved LinkedIn posts found.")
        return 0

    published = 0
    for approval_path in approved_files:
        print(f"[linkedin-poster] Processing approved: {approval_path.name}")
        content = approval_path.read_text(encoding="utf-8")

        # Extract post text between "## Post Content" and "---"
        match = re.search(
            r"## Post Content\s*\n+([\s\S]+?)\n---", content
        )
        if not match:
            print(f"[linkedin-poster] [!] Could not parse post text in {approval_path.name}")
            continue

        post_text = match.group(1).strip()
        success = post_to_linkedin(post_text)

        # Update meta
        meta_path = Path(str(approval_path) + ".meta.json")
        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["status"] = "posted" if success else "failed"
        meta["posted_at"] = datetime.now(timezone.utc).isoformat()
        meta["success"] = success

        # Move to done/
        done_path = DONE_DIR / approval_path.name
        shutil.move(str(approval_path), str(done_path))
        if meta_path.exists():
            shutil.move(str(meta_path), str(DONE_DIR / meta_path.name))

        # Write updated meta in done/
        (DONE_DIR / meta_path.name).write_text(json.dumps(meta, indent=2), encoding="utf-8")

        if success:
            update_dashboard(meta.get("title", approval_path.stem), "posted")
            log_activity(f"LinkedIn post published: {meta.get('title', approval_path.stem)}")
            published += 1
        else:
            log_activity(f"LinkedIn post FAILED: {meta.get('title', approval_path.stem)}")

    return published


# ── Dashboard + logs ──────────────────────────────────────────────────────────
def update_dashboard(title: str, status: str) -> None:
    """Add a row to the 'Recent LinkedIn Posts' table in dashboard.md."""
    if not DASHBOARD_FILE.exists():
        return

    text = DASHBOARD_FILE.read_text(encoding="utf-8")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    idx = len(list(re.finditer(r"^\| \d+", text, re.MULTILINE))) + 1
    row = f"| {idx} | {title[:50]} | {status} | {date_str} |"

    marker = "## Recent LinkedIn Posts"
    if marker in text:
        # Insert after the table separator row (the |---|...| line)
        section = text[text.find(marker):]
        sep_match = re.search(r"(\|[-| ]+\|\n)", section)
        if sep_match:
            insert_offset = text.find(marker) + sep_match.end()
            text = text[:insert_offset] + row + "\n" + text[insert_offset:]
        else:
            text = text.replace(marker, marker + f"\n{row}", 1)
    else:
        text += f"\n\n{marker}\n\n| # | Topic | Status | Date |\n|---|-------|--------|------|\n{row}\n"

    DASHBOARD_FILE.write_text(text, encoding="utf-8")


def log_activity(message: str) -> None:
    """Append a timestamped entry to system_logs.md."""
    if not SYSTEM_LOGS_FILE.exists():
        SYSTEM_LOGS_FILE.write_text("# System Logs\n\n## Activity Logs\n", encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat()
    entry = f"- [{now}] [linkedin-poster] {message}\n"
    text = SYSTEM_LOGS_FILE.read_text(encoding="utf-8")
    marker = "## Activity Logs"
    if marker in text:
        text = text.replace(marker, marker + "\n" + entry, 1)
    else:
        text += f"\n{marker}\n{entry}"
    SYSTEM_LOGS_FILE.write_text(text, encoding="utf-8")


# ── Main entry point ──────────────────────────────────────────────────────────
def run(topic: str | None = None, post_approved: bool = False) -> int:
    """
    Main entry point for the LinkedIn poster skill.

    Args:
        topic:        Optional topic override for the post.
        post_approved: If True, scan Approved/ and post waiting items instead
                       of generating a new draft.

    Returns:
        Number of posts generated (draft mode) or published (approved mode).
    """
    if post_approved:
        print("[linkedin-poster] Mode: post approved items")
        count = process_approved()
        print(f"[linkedin-poster] Published {count} post(s).")
        return count

    print("[linkedin-poster] Mode: generate new post draft")

    # Step 1: Read context
    goals = read_business_goals()
    plans = read_recent_plans(n=3)
    print(f"[linkedin-poster] Loaded {len(plans)} recent plan(s).")

    # Step 2: Generate post
    post = generate_post(topic=topic, goals=goals, plans=plans)
    print(f"[linkedin-poster] Generated post: '{post['subject']}'")
    print(f"[linkedin-poster] Sensitive: {post['sensitive']}")

    # Step 3: Create approval file (always — LinkedIn posts are external actions)
    approval_path = create_approval_file(post)
    print(f"[linkedin-poster] Approval file -> {approval_path}")

    # Step 4: Log to dashboard (as pending)
    update_dashboard(post["subject"], "pending approval")
    log_activity(f"Post draft created: '{post['subject']}' → {approval_path.name}")

    print(
        f"\n[linkedin-poster] Done.\n"
        f"  Post saved to: {approval_path}\n"
        f"  To approve:    move to Approved/\n"
        f"  To reject:     move to Rejected/\n"
        f"  To post:       run with post_approved=True after approving\n"
    )
    return 1


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    args = sys.argv[1:]
    if "post_approved" in args:
        run(post_approved=True)
    elif args:
        run(topic=" ".join(args))
    else:
        run()
