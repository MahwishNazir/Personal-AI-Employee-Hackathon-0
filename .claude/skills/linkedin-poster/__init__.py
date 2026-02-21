"""
LinkedIn Poster Skill
=====================
Generates professional LinkedIn posts from Business_Goals.md and recent plans,
routes them through human-in-the-loop approval, then posts via Playwright.

Quick start:
    from .linkedin_poster import run
    run()                          # generate draft → Pending_Approval/
    run(topic="AI automation")     # generate on specific topic
    run(post_approved=True)        # post items waiting in Approved/
"""

from .linkedin_poster import run, generate_post, create_approval_file, process_approved

__all__ = ["run", "generate_post", "create_approval_file", "process_approved"]
