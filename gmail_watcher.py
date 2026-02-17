"""
gmail_watcher.py - Gmail Notification Watcher

Monitors a Gmail inbox for unread important emails using the Gmail API.
Creates .md task files in needs_action/ with type 'email', which then
flow through the standard pipeline:
  watcher → analyzer → agent → done/

Setup:
    1. Enable the Gmail API in Google Cloud Console
    2. Create OAuth 2.0 credentials (Desktop app)
    3. Download the client secret JSON as 'client_secret.json'
    4. Run:  python gmail_watcher.py --auth
       This opens a browser for consent and saves 'gmail_token.json'
    5. Run:  python gmail_watcher.py

Requirements:
    pip install google-auth google-auth-oauthlib google-api-python-client
"""

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from base_watcher import BaseWatcher
from datetime import datetime, timezone
from pathlib import Path
import base64
import re

# If modifying scopes, delete gmail_token.json and re-auth
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailWatcher(BaseWatcher):
    """
    Watches Gmail for unread important emails.
    Creates .md task files in needs_action/ for the pipeline to process.
    """

    def __init__(self, vault_path: str, credentials_path: str):
        super().__init__(vault_path, check_interval=120)
        self.credentials_path = Path(credentials_path)
        self.creds = self._load_credentials()
        self.service = build("gmail", "v1", credentials=self.creds)
        self.processed_ids: set[str] = set()

    def _load_credentials(self) -> Credentials:
        """Load saved credentials and refresh if expired."""
        creds = Credentials.from_authorized_user_file(
            str(self.credentials_path), SCOPES
        )
        if creds and creds.expired and creds.refresh_token:
            self.logger.info("Refreshing expired credentials...")
            creds.refresh(Request())
            # Save the refreshed token back
            self.credentials_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def _get_header(self, headers: list[dict], name: str) -> str:
        """Extract a single header value by name."""
        for h in headers:
            if h["name"].lower() == name.lower():
                return h["value"]
        return ""

    def _extract_body(self, payload: dict) -> str:
        """
        Recursively extract the plain-text body from a Gmail message payload.
        Falls back to HTML body stripped of tags if no plain text is available.
        """
        # Single-part message
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        # Multipart — recurse into parts
        parts = payload.get("parts", [])

        # Prefer text/plain
        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

        # Fallback to text/html, strip tags
        for part in parts:
            if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                return re.sub(r"<[^>]+>", "", html).strip()

        # Nested multipart (e.g. multipart/alternative inside multipart/mixed)
        for part in parts:
            if part.get("parts"):
                result = self._extract_body(part)
                if result:
                    return result

        return ""

    def _classify_email(self, subject: str, sender: str, labels: list[str]) -> str:
        """Classify an email into a priority/category."""
        lower = f"{subject} {sender}".lower()
        label_str = " ".join(labels).lower()

        if "invoice" in lower or "payment" in lower or "receipt" in lower:
            return "finance"
        if "urgent" in lower or "asap" in lower or "critical" in lower:
            return "urgent"
        if "meeting" in lower or "calendar" in lower or "invite" in lower:
            return "meeting"
        if "job" in lower or "opportunity" in lower or "hiring" in lower:
            return "job"
        if "IMPORTANT" in label_str:
            return "important"
        return "general"

    def check_for_updates(self) -> list:
        """
        Query Gmail for unread important messages.
        Returns a list of message stubs not yet processed.
        """
        try:
            results = self.service.users().messages().list(
                userId="me",
                q="is:unread is:important",
                maxResults=20,
            ).execute()
        except Exception as e:
            self.logger.error(f"Gmail API list error: {e}")
            # Try to refresh credentials and rebuild service
            try:
                self.creds = self._load_credentials()
                self.service = build("gmail", "v1", credentials=self.creds)
            except Exception:
                pass
            return []

        messages = results.get("messages", [])
        new_messages = [m for m in messages if m["id"] not in self.processed_ids]

        if new_messages:
            self.logger.info(f"Found {len(new_messages)} new email(s)")

        return new_messages

    def create_action_file(self, message) -> Path:
        """
        Fetch full message details from Gmail API and create a .md task
        file with metadata sidecar in needs_action/.
        """
        msg_id = message["id"]

        try:
            msg = self.service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
        except Exception as e:
            self.logger.error(f"Failed to fetch message {msg_id}: {e}")
            self.processed_ids.add(msg_id)
            return Path()

        headers = msg.get("payload", {}).get("headers", [])
        sender = self._get_header(headers, "From")
        subject = self._get_header(headers, "Subject") or "No Subject"
        date = self._get_header(headers, "Date")
        to = self._get_header(headers, "To")
        cc = self._get_header(headers, "Cc")
        labels = msg.get("labelIds", [])

        # Extract body content
        body = self._extract_body(msg.get("payload", {}))
        snippet = msg.get("snippet", "")
        display_body = body[:2000] if body else snippet

        # Classify
        category = self._classify_email(subject, sender, labels)
        now = datetime.now(timezone.utc)

        # Check for attachments
        attachments = []
        for part in msg.get("payload", {}).get("parts", []):
            filename = part.get("filename")
            if filename:
                attachments.append(filename)

        # Build the task file
        safe_subject = re.sub(r'[^\w\-]', '_', subject)[:50]
        filename = f"EMAIL_{safe_subject}_{msg_id[:8]}.md"

        attachment_section = ""
        if attachments:
            attachment_section = "\n## Attachments\n" + "\n".join(
                f"- {a}" for a in attachments
            ) + "\n"

        content = (
            f"---\n"
            f"type: email\n"
            f"from: {sender}\n"
            f"to: {to}\n"
            f"cc: {cc}\n"
            f"subject: {subject}\n"
            f"date: {date}\n"
            f"received: {now.isoformat()}\n"
            f"category: {category}\n"
            f"priority: {'high' if category in ('urgent', 'finance') else 'normal'}\n"
            f"labels: {', '.join(labels)}\n"
            f"status: pending\n"
            f"---\n\n"
            f"# {subject}\n\n"
            f"**From:** {sender}\n"
            f"**Date:** {date}\n"
            f"**Category:** {category}\n\n"
            f"## Email Content\n\n{display_body}\n"
            f"{attachment_section}\n"
            f"## Suggested Actions\n\n"
            f"- [ ] Reply to sender\n"
            f"- [ ] Forward to relevant party\n"
            f"- [ ] Archive after processing\n"
        )

        task_path = self.needs_action / filename
        task_path.write_text(content, encoding="utf-8")

        self.write_meta(task_path, meta_extra={
            "type": "email",
            "gmail_id": msg_id,
            "from": sender,
            "subject": subject,
            "category": category,
            "labels": labels,
            "has_attachments": len(attachments) > 0,
        })

        self.processed_ids.add(msg_id)
        self.logger.info(f"New task: {filename} (from: {sender}, category: {category})")
        return task_path


# ── OAuth setup helper ─────────────────────────────────────────────────────
def run_auth_flow(client_secret_path: str, token_path: str) -> None:
    """
    Run the OAuth 2.0 consent flow in the browser and save the
    resulting token to disk.
    """
    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
    creds = flow.run_local_server(port=0)
    Path(token_path).write_text(creds.to_json(), encoding="utf-8")
    print(f"[GmailWatcher] Credentials saved to {token_path}")


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    vault = str(Path(__file__).parent)
    token_path = str(Path(__file__).parent / "gmail_token.json")
    client_secret = str(Path(__file__).parent / "client_secret.json")

    # First run: authenticate and save token
    if "--auth" in sys.argv:
        print("[GmailWatcher] Starting OAuth flow...")
        print(f"               Client secret: {client_secret}")
        run_auth_flow(client_secret, token_path)
        print("[GmailWatcher] Done. Run without --auth to start watching.")
        sys.exit(0)

    if not Path(token_path).exists():
        print("[GmailWatcher] No token found. Run with --auth first:")
        print(f"  python {__file__} --auth")
        sys.exit(1)

    watcher = GmailWatcher(vault_path=vault, credentials_path=token_path)
    watcher.run()
