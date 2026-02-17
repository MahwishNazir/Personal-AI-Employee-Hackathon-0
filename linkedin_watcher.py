"""
linkedin_watcher.py - LinkedIn Notification Watcher

Monitors LinkedIn for new notifications (messages, connection requests,
post engagement, mentions, job alerts) using Playwright with a persistent
Chromium session.

For each relevant notification it creates a .md task file in needs_action/
with type 'linkedin', which then flows through the standard pipeline:
  watcher → analyzer → agent → done/

Requirements:
    pip install playwright
    python -m playwright install chromium

Usage:
    # First run — log in to LinkedIn and save the session:
    python linkedin_watcher.py --login

    # Then start watching:
    python linkedin_watcher.py
"""

from playwright.sync_api import sync_playwright
from base_watcher import BaseWatcher
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import re


class LinkedInWatcher(BaseWatcher):
    """
    Watches LinkedIn notifications for actionable items.
    Creates .md task files in needs_action/ for the pipeline to process.
    """

    LINKEDIN_URL = "https://www.linkedin.com"
    NOTIFICATIONS_URL = "https://www.linkedin.com/notifications/"
    WAIT_TIMEOUT = 60_000  # ms to wait for page load

    # Notification types we care about
    PRIORITY_KEYWORDS = [
        "message", "mentioned", "commented", "connection",
        "replied", "invited", "endorsed", "job", "hiring",
        "opportunity", "congratulate", "posted", "shared",
    ]

    def __init__(self, vault_path: str, session_path: str):
        super().__init__(vault_path, check_interval=60)
        self.session_path = Path(session_path)
        self.session_path.mkdir(parents=True, exist_ok=True)

    def _notification_id(self, text: str) -> str:
        """Generate a stable short ID for deduplication."""
        return hashlib.sha256(text[:200].encode()).hexdigest()[:12]

    def _classify_notification(self, text: str) -> str:
        """Classify a notification into a category based on its content."""
        lower = text.lower()
        categories = {
            "message":    ["message", "sent you", "inbox"],
            "connection": ["connection", "connect", "invitation", "invited"],
            "engagement": ["commented", "replied", "liked", "reacted", "mentioned"],
            "job":        ["job", "hiring", "opportunity", "recruiter", "position"],
            "post":       ["posted", "shared", "article", "published"],
            "endorsement":["endorsed", "skill", "congratulate"],
        }
        for category, keywords in categories.items():
            if any(kw in lower for kw in keywords):
                return category
        return "general"

    def _extract_notifications(self, page) -> list[dict]:
        """
        Parse the LinkedIn notifications page and return a list of
        notification dicts with text, time, and actor info.
        """
        notifications = []

        # LinkedIn wraps each notification in an .nt-card or article element
        selectors = [
            "article.nt-card",
            ".nt-card",
            "[data-finite-scroll-hotkey-item]",
            ".notification-card",
        ]

        cards = []
        for selector in selectors:
            cards = page.query_selector_all(selector)
            if cards:
                break

        # Fallback: grab list items from the notification feed
        if not cards:
            cards = page.query_selector_all(
                ".scaffold-finite-scroll__content > li"
            )

        for card in cards:
            try:
                text = card.inner_text().strip()
                if not text:
                    continue

                # Try to extract the actor (who triggered the notification)
                actor = ""
                actor_el = card.query_selector(
                    ".nt-card__text--bold, strong, .notification-card__text--bold"
                )
                if actor_el:
                    actor = actor_el.inner_text().strip()

                # Try to extract the time
                time_text = ""
                time_el = card.query_selector(
                    ".nt-card__time-ago, time, .notification-card__time-ago"
                )
                if time_el:
                    time_text = time_el.inner_text().strip()

                notifications.append({
                    "text": text,
                    "actor": actor,
                    "time": time_text,
                })
            except Exception:
                continue

        return notifications

    def check_for_updates(self) -> list:
        """
        Open LinkedIn notifications page via persistent Chromium session,
        scrape new notifications, and return unseen ones.
        """
        new_items = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch_persistent_context(
                    str(self.session_path), headless=True,
                )
                page = browser.pages[0] if browser.pages else browser.new_page()
                page.goto(self.NOTIFICATIONS_URL, wait_until="domcontentloaded")

                # Wait for the notification feed to render
                try:
                    page.wait_for_selector(
                        ".scaffold-finite-scroll__content, .nt-card, article",
                        timeout=self.WAIT_TIMEOUT,
                    )
                    # Let dynamic content settle
                    page.wait_for_timeout(3000)
                except Exception:
                    self.logger.warning(
                        "Timed out waiting for notifications. "
                        f"Log in first with --login ({self.session_path})"
                    )
                    browser.close()
                    return []

                raw_notifications = self._extract_notifications(page)
                browser.close()

        except Exception as e:
            self.logger.error(f"Error: {e}")
            return []

        # Filter and deduplicate
        for notif in raw_notifications:
            text = notif["text"]
            nid = self._notification_id(text)

            if nid in self._seen_ids:
                continue

            # Check if notification matches any priority keyword
            lower = text.lower()
            matched = [kw for kw in self.PRIORITY_KEYWORDS if kw in lower]
            if not matched:
                continue

            self._seen_ids.add(nid)
            notif["nid"] = nid
            notif["matched_keywords"] = matched
            notif["category"] = self._classify_notification(text)
            new_items.append(notif)

        if new_items:
            self.logger.info(f"Found {len(new_items)} new notification(s)")

        return new_items

    def create_action_file(self, item) -> Path:
        """Create a .md task file in needs_action/ for a LinkedIn notification."""
        nid = item["nid"]
        category = item["category"]
        actor = item.get("actor", "Unknown")
        text = item["text"]
        matched = item["matched_keywords"]
        notif_time = item.get("time", "")
        now = datetime.now(timezone.utc)

        safe_actor = re.sub(r'[^\w\-]', '_', actor)[:30]
        filename = f"linkedin_{category}_{safe_actor}_{nid}.md"

        content = (
            f"# LinkedIn Notification — {category.title()}\n\n"
            f"- **From:** {actor}\n"
            f"- **Category:** {category}\n"
            f"- **Notification time:** {notif_time}\n"
            f"- **Captured:** {now.isoformat()}\n"
            f"- **Matched keywords:** {', '.join(matched)}\n\n"
            f"## Content\n\n{text}\n"
        )

        task_path = self.needs_action / filename
        task_path.write_text(content, encoding="utf-8")

        self.write_meta(task_path, meta_extra={
            "type": "linkedin",
            "category": category,
            "actor": actor,
            "matched_keywords": matched,
        })

        self.logger.info(f"New task: {filename} ({category}, actor: {actor})")
        return task_path


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    vault = str(Path(__file__).parent)
    session = str(Path(__file__).parent / ".linkedin_session")

    # First run: log in to LinkedIn and save the session
    if "--login" in sys.argv:
        print("[LinkedInWatcher] Login mode — opening browser...")
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(session, headless=False)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://www.linkedin.com/login")
            input("Log in to LinkedIn, then press Enter to save session...")
            ctx.close()
        print("[LinkedInWatcher] Session saved. Run without --login to start watching.")
        sys.exit(0)

    watcher = LinkedInWatcher(vault_path=vault, session_path=session)
    watcher.run()
