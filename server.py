"""
Google Workspace Multi-Account MCP Server
-----------------------------------------
Exposes Gmail, Calendar, Drive, Docs, and Sheets operations for multiple
Google accounts via the Model Context Protocol (MCP) stdio transport.

Start with:  python server.py
Configure accounts in config.json and authenticate with: python setup_auth.py
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from auth import AuthManager
from config import get_accounts, get_client_secret_path, get_credentials_dir, load_config
from gcalendar import CalendarService
from gdocs import DocsService
from gdrive import DriveService
from gmail import GmailService
from gsheets import SheetsService

# ---------------------------------------------------------------------------
# Bootstrap: load config and auth manager at startup
# ---------------------------------------------------------------------------

try:
    _config = load_config()
    _accounts = get_accounts(_config)
    _credentials_dir = get_credentials_dir(_config)
    _client_secret_path = get_client_secret_path(_config)
    _auth = AuthManager(_credentials_dir, _client_secret_path)
except FileNotFoundError as exc:
    print(f"STARTUP ERROR: {exc}", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_creds(account_name: str):
    """Return valid credentials for an account or raise ValueError."""
    if account_name not in _accounts:
        raise ValueError(
            f"Unknown account '{account_name}'. Available: {list(_accounts.keys())}"
        )
    creds = _auth.get_credentials(account_name)
    if creds is None:
        email = _accounts[account_name].get("email", account_name)
        raise ValueError(
            f"Account '{account_name}' ({email}) is not authenticated. "
            "Run 'python setup_auth.py' to authenticate."
        )
    return creds


def _get_service(account_name: str) -> GmailService:
    return GmailService(_get_creds(account_name), account_name)


def _get_calendar(account_name: str) -> CalendarService:
    return CalendarService(_get_creds(account_name), account_name)


def _get_drive(account_name: str) -> DriveService:
    return DriveService(_get_creds(account_name), account_name)


def _get_docs(account_name: str) -> DocsService:
    return DocsService(_get_creds(account_name), account_name)


def _get_sheets(account_name: str) -> SheetsService:
    return SheetsService(_get_creds(account_name), account_name)


def _fmt(data: Any) -> list[types.TextContent]:
    if isinstance(data, str):
        return [types.TextContent(type="text", text=data)]
    return [types.TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

server = Server("google-workspace-multi")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_accounts",
            description=(
                "List all Gmail accounts configured in this MCP server, "
                "along with their authentication status."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="gmail_get_profile",
            description="Get the Gmail profile (email address, message count, thread count) for an account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account name as defined in config.json (e.g. 'personal', 'work')",
                    }
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="gmail_search",
            description=(
                "Search emails using Gmail search syntax. "
                "Searches a single account or all accounts if 'account' is omitted. "
                "Example queries: 'from:boss@company.com is:unread', 'subject:invoice has:attachment'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account to search. Omit to search all configured accounts.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Gmail search query string",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results per account (default 10, max 50)",
                        "default": 10,
                    },
                    "include_body": {
                        "type": "boolean",
                        "description": "Include full message body in results (slower). Default: false.",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="gmail_read_message",
            description="Read the full content of a Gmail message by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account that owns the message",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Gmail message ID (from search results)",
                    },
                },
                "required": ["account", "message_id"],
            },
        ),
        types.Tool(
            name="gmail_read_thread",
            description="Read all messages in a Gmail thread/conversation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account that owns the thread",
                    },
                    "thread_id": {
                        "type": "string",
                        "description": "Gmail thread ID",
                    },
                },
                "required": ["account", "thread_id"],
            },
        ),
        types.Tool(
            name="gmail_send",
            description="Send a new email from a specific Gmail account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account to send from",
                    },
                    "to": {
                        "type": "string",
                        "description": "Recipient(s), comma-separated",
                    },
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body (plain text)"},
                    "cc": {"type": "string", "description": "CC recipients, comma-separated"},
                    "bcc": {"type": "string", "description": "BCC recipients, comma-separated"},
                },
                "required": ["account", "to", "subject", "body"],
            },
        ),
        types.Tool(
            name="gmail_reply",
            description="Reply to an existing Gmail thread, keeping the conversation intact.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account to send from",
                    },
                    "thread_id": {
                        "type": "string",
                        "description": "Gmail thread ID to reply into",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "The message ID being replied to (for In-Reply-To header)",
                    },
                    "to": {
                        "type": "string",
                        "description": "Recipient(s), comma-separated",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Subject (typically Re: original subject)",
                    },
                    "body": {"type": "string", "description": "Reply body (plain text)"},
                    "cc": {"type": "string", "description": "CC recipients, comma-separated"},
                    "bcc": {"type": "string", "description": "BCC recipients, comma-separated"},
                },
                "required": ["account", "thread_id", "message_id", "to", "subject", "body"],
            },
        ),
        types.Tool(
            name="gmail_create_draft",
            description="Save an email as a draft in a specific Gmail account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account to create the draft in",
                    },
                    "to": {"type": "string", "description": "Recipient(s), comma-separated"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body (plain text)"},
                    "cc": {"type": "string", "description": "CC recipients"},
                    "bcc": {"type": "string", "description": "BCC recipients"},
                },
                "required": ["account", "to", "subject", "body"],
            },
        ),
        types.Tool(
            name="gmail_list_drafts",
            description="List draft emails in a Gmail account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "max_results": {
                        "type": "integer",
                        "description": "Max drafts to return (default 10)",
                        "default": 10,
                    },
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="gmail_list_labels",
            description="List all labels and folders in a Gmail account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"}
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="gmail_modify_labels",
            description=(
                "Add or remove labels on a Gmail message. "
                "Common label IDs: STARRED, UNREAD, INBOX, SPAM, TRASH, IMPORTANT."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "message_id": {"type": "string", "description": "Gmail message ID"},
                    "add_labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Label IDs to add (e.g. ['STARRED', 'UNREAD'])",
                    },
                    "remove_labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Label IDs to remove (e.g. ['UNREAD'])",
                    },
                },
                "required": ["account", "message_id"],
            },
        ),
        types.Tool(
            name="gmail_trash",
            description="Move a Gmail message to the Trash.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "message_id": {"type": "string", "description": "Gmail message ID"},
                },
                "required": ["account", "message_id"],
            },
        ),
        # ── Calendar tools ──────────────────────────────────────────────────
        types.Tool(
            name="calendar_list_calendars",
            description="List all Google Calendars available for an account (primary, work, shared, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="calendar_list_events",
            description=(
                "List upcoming calendar events for an account. "
                "Optionally filter by time range and calendar. "
                "Times must be in RFC3339 format, e.g. '2026-03-10T00:00:00Z'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary'). Use calendar_list_calendars to get IDs.",
                        "default": "primary",
                    },
                    "time_min": {
                        "type": "string",
                        "description": "Start of range (RFC3339). Defaults to now.",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "End of range (RFC3339). Optional.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max events to return (default 20, max 50)",
                        "default": 20,
                    },
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="calendar_search",
            description="Search for events by keyword across a calendar (title, description, location, attendees).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "query": {"type": "string", "description": "Search keyword(s)"},
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary')",
                        "default": "primary",
                    },
                    "time_min": {
                        "type": "string",
                        "description": "Start of range (RFC3339). Defaults to now.",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "End of range (RFC3339). Optional.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20,
                    },
                },
                "required": ["account", "query"],
            },
        ),
        types.Tool(
            name="calendar_get_event",
            description="Get full details of a specific calendar event by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "event_id": {"type": "string", "description": "Event ID (from list or search results)"},
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary')",
                        "default": "primary",
                    },
                },
                "required": ["account", "event_id"],
            },
        ),
        # ── Drive tools ─────────────────────────────────────────────────────
        types.Tool(
            name="drive_list_files",
            description=(
                "List or search files in Google Drive for an account. "
                "Use Drive query syntax in 'query', e.g. \"name contains 'budget'\", "
                "\"mimeType='application/vnd.google-apps.spreadsheet'\", "
                "\"'<folderId>' in parents\", \"modifiedTime > '2026-01-01T00:00:00'\"."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "query": {"type": "string", "description": "Drive query (q) string. Omit to list recent files."},
                    "max_results": {"type": "integer", "description": "Max files (default 20, max 100)", "default": 20},
                    "order_by": {"type": "string", "description": "Sort order (default 'modifiedTime desc')", "default": "modifiedTime desc"},
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="drive_get_metadata",
            description="Get metadata (name, type, owners, parents, link) for a Drive file by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "Drive file ID"},
                },
                "required": ["account", "file_id"],
            },
        ),
        types.Tool(
            name="drive_read_file",
            description=(
                "Read a Drive file's text content. Google Docs are exported as plain text, "
                "Google Sheets as CSV; other text files are downloaded directly. Binary files return an error."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "Drive file ID"},
                    "max_chars": {"type": "integer", "description": "Max characters to return (default 100000)", "default": 100000},
                },
                "required": ["account", "file_id"],
            },
        ),
        types.Tool(
            name="drive_create_folder",
            description="Create a new folder in Drive, optionally inside a parent folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "name": {"type": "string", "description": "Folder name"},
                    "parent_id": {"type": "string", "description": "Parent folder ID (optional; defaults to My Drive root)"},
                },
                "required": ["account", "name"],
            },
        ),
        types.Tool(
            name="drive_create_text_file",
            description="Create a new text-based file in Drive with the given content (default mime text/plain).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "name": {"type": "string", "description": "File name (include extension, e.g. notes.md)"},
                    "content": {"type": "string", "description": "File text content"},
                    "mime_type": {"type": "string", "description": "MIME type (default 'text/plain')", "default": "text/plain"},
                    "parent_id": {"type": "string", "description": "Parent folder ID (optional)"},
                },
                "required": ["account", "name", "content"],
            },
        ),
        types.Tool(
            name="drive_update_text_file",
            description="Overwrite the content of an existing text-based Drive file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "Drive file ID"},
                    "content": {"type": "string", "description": "New text content (replaces existing)"},
                    "mime_type": {"type": "string", "description": "MIME type (default 'text/plain')", "default": "text/plain"},
                },
                "required": ["account", "file_id", "content"],
            },
        ),
        types.Tool(
            name="drive_rename_file",
            description="Rename a Drive file or folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "Drive file ID"},
                    "new_name": {"type": "string", "description": "New name"},
                },
                "required": ["account", "file_id", "new_name"],
            },
        ),
        types.Tool(
            name="drive_move_file",
            description="Move a Drive file or folder into a different parent folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "Drive file ID"},
                    "new_parent_id": {"type": "string", "description": "Destination folder ID"},
                },
                "required": ["account", "file_id", "new_parent_id"],
            },
        ),
        types.Tool(
            name="drive_copy_file",
            description="Make a copy of a Drive file, optionally with a new name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "Drive file ID to copy"},
                    "new_name": {"type": "string", "description": "Name for the copy (optional)"},
                },
                "required": ["account", "file_id"],
            },
        ),
        types.Tool(
            name="drive_trash_file",
            description="Move a Drive file or folder to the Trash.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "Drive file ID"},
                },
                "required": ["account", "file_id"],
            },
        ),
        types.Tool(
            name="drive_share_file",
            description="Grant a person access to a Drive file by email. Role is one of: reader, commenter, writer.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "Drive file ID"},
                    "email": {"type": "string", "description": "Email address to share with"},
                    "role": {"type": "string", "description": "reader | commenter | writer (default reader)", "default": "reader"},
                    "notify": {"type": "boolean", "description": "Send notification email (default false)", "default": False},
                },
                "required": ["account", "file_id", "email"],
            },
        ),
        # ── Docs tools ──────────────────────────────────────────────────────
        types.Tool(
            name="docs_create",
            description="Create a new Google Doc with a title and optional initial plain-text body.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "title": {"type": "string", "description": "Document title"},
                    "text": {"type": "string", "description": "Initial body text (plain text, optional)"},
                },
                "required": ["account", "title"],
            },
        ),
        types.Tool(
            name="docs_read",
            description="Read the full plain-text content of a Google Doc by its document ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc document ID"},
                },
                "required": ["account", "document_id"],
            },
        ),
        types.Tool(
            name="docs_append_text",
            description="Append plain text to the end of a Google Doc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc document ID"},
                    "text": {"type": "string", "description": "Text to append"},
                },
                "required": ["account", "document_id", "text"],
            },
        ),
        types.Tool(
            name="docs_replace_text",
            description="Find and replace all occurrences of a string in a Google Doc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc document ID"},
                    "find": {"type": "string", "description": "Text to find"},
                    "replace": {"type": "string", "description": "Replacement text"},
                    "match_case": {"type": "boolean", "description": "Case-sensitive match (default true)", "default": True},
                },
                "required": ["account", "document_id", "find", "replace"],
            },
        ),
        # ── Sheets tools ────────────────────────────────────────────────────
        types.Tool(
            name="sheets_create",
            description="Create a new Google Spreadsheet with the given title.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "title": {"type": "string", "description": "Spreadsheet title"},
                },
                "required": ["account", "title"],
            },
        ),
        types.Tool(
            name="sheets_get_info",
            description="Get a spreadsheet's title, URL, and the list of its sheets/tabs (with dimensions).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                },
                "required": ["account", "spreadsheet_id"],
            },
        ),
        types.Tool(
            name="sheets_add_sheet",
            description="Add a new sheet/tab to an existing spreadsheet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "title": {"type": "string", "description": "New sheet/tab title"},
                },
                "required": ["account", "spreadsheet_id", "title"],
            },
        ),
        types.Tool(
            name="sheets_read_range",
            description="Read values from an A1 range, e.g. 'Sheet1!A1:D20'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "range": {"type": "string", "description": "A1 range, e.g. 'Sheet1!A1:D20'"},
                },
                "required": ["account", "spreadsheet_id", "range"],
            },
        ),
        types.Tool(
            name="sheets_write_range",
            description=(
                "Write a 2D array of values to an A1 range (overwrites existing cells). "
                "'values' is an array of rows, each an array of cell values."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "range": {"type": "string", "description": "A1 range, e.g. 'Sheet1!A1'"},
                    "values": {
                        "type": "array",
                        "items": {"type": "array", "items": {}},
                        "description": "2D array of rows of cell values",
                    },
                },
                "required": ["account", "spreadsheet_id", "range", "values"],
            },
        ),
        types.Tool(
            name="sheets_append_rows",
            description="Append rows after the last row of data in the given range/table.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "range": {"type": "string", "description": "A1 range/table, e.g. 'Sheet1!A1'"},
                    "values": {
                        "type": "array",
                        "items": {"type": "array", "items": {}},
                        "description": "2D array of rows to append",
                    },
                },
                "required": ["account", "spreadsheet_id", "range", "values"],
            },
        ),
        types.Tool(
            name="sheets_clear_range",
            description="Clear all values from an A1 range (formatting is preserved).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "range": {"type": "string", "description": "A1 range to clear"},
                },
                "required": ["account", "spreadsheet_id", "range"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    args = arguments or {}

    try:
        # ---- list_accounts ------------------------------------------------
        if name == "list_accounts":
            result = []
            for acct, info in _accounts.items():
                authenticated = _auth.is_authenticated(acct)
                result.append({
                    "name": acct,
                    "email": info.get("email", ""),
                    "description": info.get("description", ""),
                    "authenticated": authenticated,
                    "status": "ready" if authenticated else "not authenticated — run setup_auth.py",
                })
            return _fmt(result)

        # ---- gmail_get_profile --------------------------------------------
        elif name == "gmail_get_profile":
            svc = _get_service(args["account"])
            return _fmt(svc.get_profile())

        # ---- gmail_search -------------------------------------------------
        elif name == "gmail_search":
            query: str = args["query"]
            max_results: int = int(args.get("max_results", 10))
            include_body: bool = bool(args.get("include_body", False))
            account: str | None = args.get("account")

            if account:
                svc = _get_service(account)
                data = svc.search_messages(query, max_results, include_body=include_body)
                data["account"] = account
                data["email"] = _accounts[account].get("email", "")
                return _fmt(data)
            else:
                all_results = []
                for acct in _accounts:
                    try:
                        svc = _get_service(acct)
                        data = svc.search_messages(query, max_results, include_body=include_body)
                        all_results.append({
                            "account": acct,
                            "email": _accounts[acct].get("email", ""),
                            **data,
                        })
                    except ValueError as exc:
                        all_results.append({
                            "account": acct,
                            "error": str(exc),
                            "messages": [],
                        })
                return _fmt(all_results)

        # ---- gmail_read_message -------------------------------------------
        elif name == "gmail_read_message":
            svc = _get_service(args["account"])
            return _fmt(svc.get_message(args["message_id"]))

        # ---- gmail_read_thread --------------------------------------------
        elif name == "gmail_read_thread":
            svc = _get_service(args["account"])
            return _fmt(svc.get_thread(args["thread_id"]))

        # ---- gmail_send ---------------------------------------------------
        elif name == "gmail_send":
            svc = _get_service(args["account"])
            result = svc.send_message(
                to=args["to"],
                subject=args["subject"],
                body=args["body"],
                cc=args.get("cc", ""),
                bcc=args.get("bcc", ""),
            )
            return _fmt({
                "status": "sent",
                "message_id": result.get("id"),
                "thread_id": result.get("threadId"),
            })

        # ---- gmail_reply --------------------------------------------------
        elif name == "gmail_reply":
            svc = _get_service(args["account"])
            result = svc.reply_to_thread(
                thread_id=args["thread_id"],
                message_id=args["message_id"],
                to=args["to"],
                subject=args["subject"],
                body=args["body"],
                cc=args.get("cc", ""),
                bcc=args.get("bcc", ""),
            )
            return _fmt({
                "status": "sent",
                "message_id": result.get("id"),
                "thread_id": result.get("threadId"),
            })

        # ---- gmail_create_draft -------------------------------------------
        elif name == "gmail_create_draft":
            svc = _get_service(args["account"])
            result = svc.create_draft(
                to=args["to"],
                subject=args["subject"],
                body=args["body"],
                cc=args.get("cc", ""),
                bcc=args.get("bcc", ""),
            )
            return _fmt({"status": "draft created", "draft_id": result.get("id")})

        # ---- gmail_list_drafts --------------------------------------------
        elif name == "gmail_list_drafts":
            svc = _get_service(args["account"])
            drafts = svc.list_drafts(int(args.get("max_results", 10)))
            return _fmt({"count": len(drafts), "drafts": drafts})

        # ---- gmail_list_labels --------------------------------------------
        elif name == "gmail_list_labels":
            svc = _get_service(args["account"])
            return _fmt(svc.list_labels())

        # ---- gmail_modify_labels -----------------------------------------
        elif name == "gmail_modify_labels":
            svc = _get_service(args["account"])
            svc.modify_labels(
                message_id=args["message_id"],
                add_labels=args.get("add_labels"),
                remove_labels=args.get("remove_labels"),
            )
            return _fmt({"status": "labels updated", "message_id": args["message_id"]})

        # ---- gmail_trash -------------------------------------------------
        elif name == "gmail_trash":
            svc = _get_service(args["account"])
            svc.trash_message(args["message_id"])
            return _fmt({"status": "moved to trash", "message_id": args["message_id"]})

        # ---- calendar_list_calendars --------------------------------------
        elif name == "calendar_list_calendars":
            svc = _get_calendar(args["account"])
            return _fmt(svc.list_calendars())

        # ---- calendar_list_events -----------------------------------------
        elif name == "calendar_list_events":
            svc = _get_calendar(args["account"])
            return _fmt(svc.list_events(
                time_min=args.get("time_min"),
                time_max=args.get("time_max"),
                max_results=int(args.get("max_results", 20)),
                calendar_id=args.get("calendar_id", "primary"),
            ))

        # ---- calendar_search ----------------------------------------------
        elif name == "calendar_search":
            svc = _get_calendar(args["account"])
            return _fmt(svc.search_events(
                query=args["query"],
                time_min=args.get("time_min"),
                time_max=args.get("time_max"),
                max_results=int(args.get("max_results", 20)),
                calendar_id=args.get("calendar_id", "primary"),
            ))

        # ---- calendar_get_event -------------------------------------------
        elif name == "calendar_get_event":
            svc = _get_calendar(args["account"])
            return _fmt(svc.get_event(
                event_id=args["event_id"],
                calendar_id=args.get("calendar_id", "primary"),
            ))

        # ---- Drive --------------------------------------------------------
        elif name == "drive_list_files":
            svc = _get_drive(args["account"])
            return _fmt(svc.list_files(
                query=args.get("query"),
                max_results=int(args.get("max_results", 20)),
                order_by=args.get("order_by", "modifiedTime desc"),
            ))

        elif name == "drive_get_metadata":
            svc = _get_drive(args["account"])
            return _fmt(svc.get_metadata(args["file_id"]))

        elif name == "drive_read_file":
            svc = _get_drive(args["account"])
            return _fmt(svc.read_file(args["file_id"], int(args.get("max_chars", 100_000))))

        elif name == "drive_create_folder":
            svc = _get_drive(args["account"])
            return _fmt(svc.create_folder(args["name"], args.get("parent_id")))

        elif name == "drive_create_text_file":
            svc = _get_drive(args["account"])
            return _fmt(svc.create_text_file(
                name=args["name"],
                content=args["content"],
                mime_type=args.get("mime_type", "text/plain"),
                parent_id=args.get("parent_id"),
            ))

        elif name == "drive_update_text_file":
            svc = _get_drive(args["account"])
            return _fmt(svc.update_text_file(
                file_id=args["file_id"],
                content=args["content"],
                mime_type=args.get("mime_type", "text/plain"),
            ))

        elif name == "drive_rename_file":
            svc = _get_drive(args["account"])
            return _fmt(svc.rename_file(args["file_id"], args["new_name"]))

        elif name == "drive_move_file":
            svc = _get_drive(args["account"])
            return _fmt(svc.move_file(args["file_id"], args["new_parent_id"]))

        elif name == "drive_copy_file":
            svc = _get_drive(args["account"])
            return _fmt(svc.copy_file(args["file_id"], args.get("new_name")))

        elif name == "drive_trash_file":
            svc = _get_drive(args["account"])
            return _fmt(svc.trash_file(args["file_id"]))

        elif name == "drive_share_file":
            svc = _get_drive(args["account"])
            return _fmt(svc.share_file(
                file_id=args["file_id"],
                email=args["email"],
                role=args.get("role", "reader"),
                notify=bool(args.get("notify", False)),
            ))

        # ---- Docs ---------------------------------------------------------
        elif name == "docs_create":
            svc = _get_docs(args["account"])
            return _fmt(svc.create_document(args["title"], args.get("text")))

        elif name == "docs_read":
            svc = _get_docs(args["account"])
            return _fmt(svc.read_document(args["document_id"]))

        elif name == "docs_append_text":
            svc = _get_docs(args["account"])
            return _fmt(svc.append_text(args["document_id"], args["text"]))

        elif name == "docs_replace_text":
            svc = _get_docs(args["account"])
            return _fmt(svc.replace_text(
                document_id=args["document_id"],
                find=args["find"],
                replace=args["replace"],
                match_case=bool(args.get("match_case", True)),
            ))

        # ---- Sheets -------------------------------------------------------
        elif name == "sheets_create":
            svc = _get_sheets(args["account"])
            return _fmt(svc.create_spreadsheet(args["title"]))

        elif name == "sheets_get_info":
            svc = _get_sheets(args["account"])
            return _fmt(svc.get_info(args["spreadsheet_id"]))

        elif name == "sheets_add_sheet":
            svc = _get_sheets(args["account"])
            return _fmt(svc.add_sheet(args["spreadsheet_id"], args["title"]))

        elif name == "sheets_read_range":
            svc = _get_sheets(args["account"])
            return _fmt(svc.read_range(args["spreadsheet_id"], args["range"]))

        elif name == "sheets_write_range":
            svc = _get_sheets(args["account"])
            return _fmt(svc.write_range(args["spreadsheet_id"], args["range"], args["values"]))

        elif name == "sheets_append_rows":
            svc = _get_sheets(args["account"])
            return _fmt(svc.append_rows(args["spreadsheet_id"], args["range"], args["values"]))

        elif name == "sheets_clear_range":
            svc = _get_sheets(args["account"])
            return _fmt(svc.clear_range(args["spreadsheet_id"], args["range"]))

        else:
            return _fmt(f"Unknown tool: {name}")

    except ValueError as exc:
        return _fmt(f"Error: {exc}")
    except Exception as exc:
        return _fmt(f"Error in '{name}': {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())