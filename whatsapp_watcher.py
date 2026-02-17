"""
whatsapp_watcher.py - WhatsApp Message Watcher

Monitors WhatsApp Web for unread messages containing priority keywords.
Uses Playwright with a persistent Chromium session so you only need to
scan the QR code once.

For each matching message it creates a task file in needs_action/ with
type 'whatsapp', which then flows through the standard pipeline:
  watcher → analyzer → agent → done/

Requirements:
    pip install playwright
    python -m playwright install chromium
"""

from playwright.sync_api import sync_playwright
from base_watcher import BaseWatcher
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import re


class WhatsAppWatcher(BaseWatcher):
    """
    Watches WhatsApp Web for unread messages that match priority keywords.
    Creates task files in needs_action/ for the pipeline to process.
    """

    WHATSAPP_URL = "https://web.whatsapp.com"
    WAIT_TIMEOUT = 60_000  # ms to wait for WhatsApp to load

    def __init__(self, vault_path: str, session_path: str):
        super().__init__(vault_path, check_interval=30)
        self.session_path = Path(session_path)
        self.session_path.mkdir(parents=True, exist_ok=True)
        self.keywords = ["urgent", "invoice", "payment", "help", "price", "quote"]

    def _message_id(self, text: str, chat_name: str) -> str:
        """Generate a stable short ID for deduplication."""
        raw = f"{chat_name}:{text[:120]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _extract_chat_name(self, chat_element) -> str:
        """Try to pull the contact / group name from the chat element."""
        try:
            title = chat_element.query_selector("[data-testid='cell-frame-title'] span")
            if title:
                return title.inner_text().strip()
        except Exception:
            pass
        return "unknown_chat"

    def _extract_last_message(self, chat_element) -> str:
        """Pull the last message preview text from the chat element."""
        try:
            msg = chat_element.query_selector("[data-testid='last-msg-status'] span")
            if msg:
                return msg.inner_text().strip()
            spans = chat_element.query_selector_all("span[title]")
            for span in spans:
                text = span.get_attribute("title") or ""
                if text:
                    return text.strip()
        except Exception:
            pass
        return chat_element.inner_text().strip()

    def _matches_keywords(self, text: str) -> list[str]:
        """Return list of matched keywords found in text."""
        lower = text.lower()
        return [kw for kw in self.keywords if kw in lower]

    def check_for_updates(self) -> list:
        """
        Launch a persistent Chromium session, open WhatsApp Web,
        scan unread chats for keyword matches.

        Returns a list of dicts for each new message found.
        """
        new_messages = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch_persistent_context(
                    str(self.session_path), headless=True,
                )
                page = browser.pages[0] if browser.pages else browser.new_page()
                page.goto(self.WHATSAPP_URL, wait_until="domcontentloaded")

                try:
                    page.wait_for_selector(
                        '[data-testid="chat-list"]', timeout=self.WAIT_TIMEOUT,
                    )
                except Exception:
                    self.logger.warning(
                        "Timed out waiting for chat list. "
                        f"Scan QR in a headed session first ({self.session_path})"
                    )
                    browser.close()
                    return []

                unread_chats = page.query_selector_all('[aria-label*="unread"]')

                for chat in unread_chats:
                    chat_name = self._extract_chat_name(chat)
                    text = self._extract_last_message(chat)
                    matched_kw = self._matches_keywords(text)

                    if not matched_kw:
                        continue

                    msg_id = self._message_id(text, chat_name)
                    if msg_id in self._seen_ids:
                        continue
                    self._seen_ids.add(msg_id)

                    new_messages.append({
                        "chat": chat_name,
                        "text": text,
                        "keywords": matched_kw,
                        "msg_id": msg_id,
                    })

                browser.close()

        except Exception as e:
            self.logger.error(f"Error: {e}")

        return new_messages

    def create_action_file(self, item) -> Path:
        """Create a .md task file in needs_action/ for a WhatsApp message."""
        chat_name = item["chat"]
        text = item["text"]
        matched_kw = item["keywords"]
        msg_id = item["msg_id"]
        now = datetime.now(timezone.utc)

        safe_name = re.sub(r'[^\w\-]', '_', chat_name)[:40]
        filename = f"whatsapp_{safe_name}_{msg_id}.md"

        content = (
            f"# WhatsApp Message — {chat_name}\n\n"
            f"- **From:** {chat_name}\n"
            f"- **Received:** {now.isoformat()}\n"
            f"- **Keywords:** {', '.join(matched_kw)}\n\n"
            f"## Message\n\n{text}\n"
        )

        task_path = self.needs_action / filename
        task_path.write_text(content, encoding="utf-8")

        meta_path = self.write_meta(task_path, meta_extra={
            "type": "whatsapp",
            "source_chat": chat_name,
            "matched_keywords": matched_kw,
        })

        self.logger.info(f"New task: {filename} (chat: {chat_name})")
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
    session = str(Path(__file__).parent / ".whatsapp_session")

    # First run: use headed mode so you can scan the QR code
    if "--login" in sys.argv:
        print("[WhatsAppWatcher] Login mode — opening browser for QR scan...")
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(session, headless=False)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://web.whatsapp.com")
            input("Scan the QR code, then press Enter to save session...")
            ctx.close()
        print("[WhatsAppWatcher] Session saved. Run without --login to start watching.")
        sys.exit(0)

    watcher = WhatsAppWatcher(vault_path=vault, session_path=session)
    watcher.run()
