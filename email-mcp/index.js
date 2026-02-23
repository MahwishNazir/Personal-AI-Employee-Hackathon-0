#!/usr/bin/env node
/**
 * email-mcp — Gmail MCP Server
 *
 * Exposes a `send_email` tool to Claude Code via the Model Context Protocol.
 * Uses the Gmail API (v1) with OAuth2 credentials loaded from a token.json file.
 *
 * ─── QUICK START ──────────────────────────────────────────────────────────────
 *  1. npm install
 *  2. Set GMAIL_CREDENTIALS=./token.json  (or in a .env file)
 *  3. node index.js
 * ──────────────────────────────────────────────────────────────────────────────
 */

import "dotenv/config";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { google } from "googleapis";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ── Logging (to stderr so it doesn't pollute MCP stdio) ─────────────────────
const log = {
  info:  (...args) => console.error("[email-mcp] INFO:", ...args),
  warn:  (...args) => console.error("[email-mcp] WARN:", ...args),
  error: (...args) => console.error("[email-mcp] ERROR:", ...args),
};

// ── Gmail OAuth2 Setup ───────────────────────────────────────────────────────
const SCOPES = ["https://www.googleapis.com/auth/gmail.send"];

function loadCredentials() {
  const credPath = process.env.GMAIL_CREDENTIALS || path.join(__dirname, "token.json");

  if (!fs.existsSync(credPath)) {
    throw new Error(
      `Gmail credentials not found at: ${credPath}\n` +
      `Set GMAIL_CREDENTIALS env var to the path of your token.json file.\n` +
      `Run the Python auth flow first: python gmail_watcher.py --auth`
    );
  }

  const raw = fs.readFileSync(credPath, "utf-8");
  return JSON.parse(raw);
}

function buildGmailClient() {
  const creds = loadCredentials();

  const oauth2 = new google.auth.OAuth2(
    creds.client_id,
    creds.client_secret,
    creds.redirect_uri ?? "urn:ietf:wg:oauth:2.0:oob"
  );

  oauth2.setCredentials({
    access_token:  creds.access_token,
    refresh_token: creds.refresh_token,
    token_type:    creds.token_type,
    expiry_date:   creds.expiry_date,
  });

  return google.gmail({ version: "v1", auth: oauth2 });
}

// ── Email builder ────────────────────────────────────────────────────────────

/**
 * Build a RFC 2822 MIME message and encode it as base64url for Gmail API.
 */
function buildMimeMessage({ to, subject, body, html, cc, bcc, attachments }) {
  const boundary = `boundary_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  const isHtml = html === true;
  const contentType = isHtml ? "text/html" : "text/plain";
  const hasAttachments = attachments && attachments.length > 0;

  // Normalise cc/bcc to comma strings
  const ccStr  = Array.isArray(cc)  ? cc.join(", ")  : (cc  ?? "");
  const bccStr = Array.isArray(bcc) ? bcc.join(", ") : (bcc ?? "");

  const headers = [
    `To: ${to}`,
    `Subject: ${subject}`,
    ccStr  ? `Cc: ${ccStr}`   : null,
    bccStr ? `Bcc: ${bccStr}` : null,
    "MIME-Version: 1.0",
  ].filter(Boolean);

  let mime;

  if (!hasAttachments) {
    // Simple single-part message
    mime = [
      ...headers,
      `Content-Type: ${contentType}; charset="UTF-8"`,
      "",
      body,
    ].join("\r\n");
  } else {
    // Multipart/mixed for attachments
    headers.push(`Content-Type: multipart/mixed; boundary="${boundary}"`);

    const parts = [
      `--${boundary}`,
      `Content-Type: ${contentType}; charset="UTF-8"`,
      "Content-Transfer-Encoding: quoted-printable",
      "",
      body,
    ];

    for (const att of attachments) {
      const attContent = att.content;           // base64 string or file path
      let   attData    = attContent;

      // If it looks like a file path, read and encode it
      if (!attContent.includes("=") && fs.existsSync(attContent)) {
        attData = fs.readFileSync(attContent).toString("base64");
      }

      parts.push(
        `--${boundary}`,
        `Content-Type: application/octet-stream; name="${att.filename}"`,
        "Content-Transfer-Encoding: base64",
        `Content-Disposition: attachment; filename="${att.filename}"`,
        "",
        attData
      );
    }

    parts.push(`--${boundary}--`);
    mime = [...headers, "", ...parts].join("\r\n");
  }

  // Gmail API requires base64url encoding (no padding)
  return Buffer.from(mime)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

// ── send_email handler ───────────────────────────────────────────────────────
async function sendEmail(args) {
  const { to, subject, body, html, cc, bcc, attachments } = args;

  // Validate required fields
  if (!to || !subject || !body) {
    throw new Error("Missing required fields: to, subject, body");
  }

  log.info(`Sending email to="${to}" subject="${subject}" html=${!!html}`);

  const gmail  = buildGmailClient();
  const raw    = buildMimeMessage({ to, subject, body, html, cc, bcc, attachments });

  const response = await gmail.users.messages.send({
    userId:      "me",
    requestBody: { raw },
  });

  log.info(`Email sent — Gmail message ID: ${response.data.id}`);

  return {
    success:   true,
    messageId: response.data.id,
    threadId:  response.data.threadId,
    to,
    subject,
    timestamp: new Date().toISOString(),
  };
}

// ── Tool schema ──────────────────────────────────────────────────────────────
const SEND_EMAIL_TOOL = {
  name: "send_email",
  description:
    "Send an email via Gmail. Supports plain text and HTML bodies, CC/BCC, and file attachments.",
  inputSchema: {
    type: "object",
    properties: {
      to: {
        type: "string",
        description: "Recipient email address (required)",
      },
      subject: {
        type: "string",
        description: "Email subject line (required)",
      },
      body: {
        type: "string",
        description: "Email body — plain text or HTML depending on the `html` flag (required)",
      },
      html: {
        type: "boolean",
        description: "If true, the body is sent as HTML. Default: false",
        default: false,
      },
      cc: {
        oneOf: [
          { type: "string" },
          { type: "array", items: { type: "string" } },
        ],
        description: "CC recipient(s) — a single address or array of addresses",
      },
      bcc: {
        oneOf: [
          { type: "string" },
          { type: "array", items: { type: "string" } },
        ],
        description: "BCC recipient(s) — a single address or array of addresses",
      },
      attachments: {
        type: "array",
        description: "File attachments",
        items: {
          type: "object",
          properties: {
            filename: {
              type: "string",
              description: "Name of the attachment as it appears in the email",
            },
            content: {
              type: "string",
              description: "Base64-encoded file content OR an absolute file path on disk",
            },
          },
          required: ["filename", "content"],
        },
      },
    },
    required: ["to", "subject", "body"],
  },
};

// ── MCP Server setup ─────────────────────────────────────────────────────────
const server = new Server(
  { name: "email-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

// List available tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return { tools: [SEND_EMAIL_TOOL] };
});

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name !== "send_email") {
    return {
      content: [{ type: "text", text: `Unknown tool: ${name}` }],
      isError: true,
    };
  }

  try {
    const result = await sendEmail(args);
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  } catch (err) {
    log.error("send_email failed:", err.message);
    return {
      content: [
        {
          type: "text",
          text: `Failed to send email: ${err.message}`,
        },
      ],
      isError: true,
    };
  }
});

// ── Start ────────────────────────────────────────────────────────────────────
async function main() {
  log.info("Starting email-mcp server...");

  // Validate credentials are loadable at startup
  try {
    loadCredentials();
    log.info("Gmail credentials loaded successfully.");
  } catch (err) {
    log.error(err.message);
    process.exit(1);
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);
  log.info("email-mcp server running on stdio.");
}

main().catch((err) => {
  log.error("Fatal:", err);
  process.exit(1);
});
