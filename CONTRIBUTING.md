# Contributing

Thanks for your interest in improving this project. It's a small, self-hosted MCP server, so the bar is simple: keep it easy to run locally and easy to read.

## Development setup

```bash
git clone https://github.com/illogicalproject/google-workspace-multi-mcp.git
cd google-workspace-multi-mcp
bash setup.sh
source .venv/bin/activate
```

Then create your own Google Cloud OAuth client and `config.json` as described in the [README](README.md), and run `python setup_auth.py`.

## Project layout

- `server.py` — MCP server: tool definitions (`list_tools`) and dispatch (`call_tool`).
- `auth.py` — OAuth: `SERVICE_SCOPES`, `build_scopes()`, and `AuthManager` (token storage/refresh).
- `config.py` — loads `config.json` (accounts, enabled services, paths).
- `gmail.py`, `gcalendar.py`, `gdrive.py`, `gdocs.py`, `gsheets.py` — one service wrapper each, built on `googleapiclient`.
- `setup_auth.py` — one-time interactive OAuth flow per account.

## Adding a tool

1. Add a method to the relevant service wrapper (e.g. `gdrive.py`).
2. Register the tool in `server.py` → `list_tools()` (follow the existing `types.Tool(...)` pattern; name it `<service>_<verb>` so service-gating picks it up).
3. Add a matching branch in `server.py` → `call_tool()`.
4. If it needs a new scope, add it to the right service in `auth.py` `SERVICE_SCOPES`; users will need to re-run `setup_auth.py`.

## Conventions

- Every tool takes an `account` parameter matching a key in `config.json`.
- Match the existing style — small wrapper methods returning plain dicts; no heavy abstractions.
- Google API gotcha: the **Sheets** API rejects whitespace in `fields` masks (e.g. `"a, b"`); Drive tolerates it. Keep Sheets field masks space-free.

## Security

- **Never commit `credentials/` or `config.json`.** They're gitignored — keep it that way. No real OAuth client IDs, secrets, tokens, or personal emails in commits, tests, or docs.

## Pull requests

Keep PRs focused. Run `python -m py_compile *.py` before pushing. Describe what you changed and how you tested it (a local round-trip against a real account is ideal).
