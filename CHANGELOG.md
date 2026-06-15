# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [0.2.0] - 2026-06-15

### Added
- **Google Drive, Docs, and Sheets** support with full read/write, across all configured
  accounts (22 new tools): Drive file management + content read/write, Doc
  create/read/append/find-replace, Sheet create/read/write/append.
- **Configurable services** — an optional `services` list in `config.json` controls which
  services are enabled (both the OAuth scopes requested and the tools exposed). Supports a
  `drive.file` option for per-file, non-restricted Drive access.
- `LICENSE` (MIT) and `CONTRIBUTING.md`.

### Changed
- Renamed the project to **google-workspace-multi-mcp** (was `gmail-mcp`) to reflect the
  broader Google Workspace coverage; rewrote the README, including an upfront explanation of
  the unverified-app consent warning.

### Fixed
- Sheets API `fields` masks must be whitespace-free (Drive tolerates whitespace; Sheets does not).

## [0.1.0]

### Added
- Initial multi-account server for **Gmail** (search, read, send, reply, drafts, labels, trash)
  and **Google Calendar** (read: list, browse, search events).
