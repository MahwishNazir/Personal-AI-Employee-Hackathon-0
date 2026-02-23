"""
auth.py — OAuth 2.0 flow for email-mcp

Requests gmail.send scope and writes email-mcp/token.json in the
format expected by index.js:
  { access_token, refresh_token, token_type, expiry_date, client_id, client_secret }

Usage:
    python email-mcp/auth.py
"""

import json
import time
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

ROOT = Path(__file__).parent.parent
CLIENT_SECRET = ROOT / "client_secret.json"
TOKEN_OUT = Path(__file__).parent / "token.json"


def main():
    print(f"[email-mcp auth] Using client secret: {CLIENT_SECRET}")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0)

    # Convert to the format index.js expects
    expiry_date = None
    if creds.expiry:
        expiry_date = int(creds.expiry.timestamp() * 1000)  # milliseconds

    token_data = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_type": "Bearer",
        "expiry_date": expiry_date,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": SCOPES,
    }

    TOKEN_OUT.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
    print(f"[email-mcp auth] Token saved to {TOKEN_OUT}")
    print("[email-mcp auth] Done. You can now use the send_email MCP tool.")


if __name__ == "__main__":
    main()
