# imexp

An interactive CLI wrapper for [imessage-exporter](https://github.com/ReagentX/imessage-exporter) that adds contact name resolution and post-processing to your iMessage exports.

## Features

- **Saved profiles** — define client/project presets in `config.ini` and run `imexp` with no selector
- **Strict conversation filters** — resolve exact handles locally before calling `imessage-exporter`
- **Selector preflight** — inspect the resolved handles and matching chats before export
- **Exact selector mode** — refuse exports when union filtering would broaden beyond the selected participant set
- **Interactive wizard** — run `imexp --wizard` or `imexp export --wizard` for a guided export
- **Natural language dates** — use phrases like "last 6 months" or "2 weeks ago"
- **Contact resolution** — automatically maps phone numbers and emails to names from your macOS or iOS Contacts database
- **iOS backup support** — auto-detects backups and lets you pick by device name/date
- **Post-processing** — renames exported files and replaces raw handles with contact names
- **Export history** — tracks your last export date to avoid duplicates

## Requirements

- Python 3.12+
- macOS or Windows for the official wheels

macOS local Address Book lookups require macOS. iOS backup exports work on both macOS and Windows.

## Installation

Install from PyPI:

```bash
pip install imexp
```

Official wheels bundle the matching `imessage-exporter` binary for:

- macOS Apple Silicon
- macOS Intel
- Windows x86_64

Source installs do not bundle the exporter binary. For editable or source installs, either:

- install `imessage-exporter` separately and keep it on `PATH`
- point `IMEXP_EXPORTER_PATH` at a local binary

Example source install:

```bash
git clone https://github.com/code-switched/imexp.git
cd imexp
pip install -e .
```

## Usage

### Interactive mode

If you do not configure a default profile, running `imexp` or `imexp export` with no arguments
starts the guided wizard:

```bash
imexp
```

To force the wizard even when a default profile exists:

```bash
imexp --wizard
```

The wizard prompts for:
- Platform (macOS or iOS backup)
- Date range (natural language supported)
- Export location

### Command-line mode

```bash
imexp export --start-date "2024-01-01" --end-date "2024-06-01" --format txt
```

### Saved profiles

Profiles let you define the handles you care about for a client or project and reuse them across
repositories.

Canonical example: [data/config/imexp/config.example.ini](/Users/dev/code/tools/imexp/data/config/imexp/config.example.ini)

Example contents:

```ini
[export]
default_profile = client-a
output_dir = ./data/messages/sms

[profile.client-a]
handles =
    +15551234567
    client@example.com
names =
    Client Contact
    Alternate Contact Label
label = Client Contact
slug = client-contact
platform = macOS
format = txt
copy_method = full
use_caller_id = true
```

Then run:

```bash
imexp
```

Or select a profile explicitly:

```bash
imexp export --profile client-a --start-date "last 30 days"
```

By default, selector mode is `union`: any chat containing one of the selected handles is included
because upstream filtering is participant-union based.

To make that safe for client-context exports, use:

```bash
imexp export --profile client-a --selector-preflight
imexp export --profile client-a --selector-mode exact
```

`--selector-preflight` prints the resolved handles plus the exact chat sets that would match.
`--selector-mode exact` refuses the export if any matched chat would bring in participants outside
the selected handle set.

Profile fields:

- `handles` are the canonical selectors used for export filtering.
- `names` are optional display aliases used only for filename normalization.
- `label` is the human-friendly display name for that profile.
- `slug` is the optional folder-name override. If omitted, it is derived from `label` or the
  profile key.

### Strict filter behavior

`--conversation-filter` no longer passes raw free text straight through to upstream name matching.

- Exact handles are normalized and matched locally first.
- Exact contact names are matched case-insensitively and rewritten to canonical handles.
- Ambiguous names fail and print the candidate handles.
- No-match filters fail instead of broadening the export.

Examples:

```bash
imexp export --conversation-filter "+1 (555) 123-4567"
imexp export --conversation-filter "Alice Smith"
```

### Relabel existing exports

Re-run contact resolution on a previous export:

```bash
imexp relabel --export-path ./data/messages/sms/2024-01-15-10-30-00
```

### Common options

| Option | Description |
|--------|-------------|
| `--start-date` | Start date (natural language or YYYY-MM-DD) |
| `--end-date` | End date (defaults to now) |
| `--format` | Output format: `txt`, `html` (default: `txt`) |
| `--platform` | `macOS` or `iOS` |
| `--db-path` | Path to iOS backup or custom chat.db |
| `--export-path` | Custom output directory |
| `--selector-mode` | Selector safety mode: `union` or `exact` |
| `--selector-preflight` | Print selector resolution and matching chats without exporting |
| `--non-interactive` | Disable prompts for scripted use |
| `-v, --verbose` | Enable debug logging |

## How it works

1. Runs `imessage-exporter` with your specified options
2. Loads contacts from macOS Contacts.app or iOS backup
3. Post-processes exported files:
   - Renames files from phone numbers to contact names
   - Replaces raw handles in file contents with names
4. Saves unknown number → name mappings to `contacts.json` for future exports
5. Tracks export history in `history.json` for incremental exports

## Configuration files

By default, repo-local files are stored under `./data/`:

- `contacts.json` — custom name overrides for unknown numbers
- `history.json` — tracks last export date
- `config/imexp/config.ini` — export defaults and saved profiles

See [docs/dev/client-context.md](./docs/dev/client-context.md) for the design note behind the
client-context workflow this tool is aiming at.

## License

`imexp` is distributed under `GPL-3.0-or-later`.

The official wheels bundle the upstream `imessage-exporter` binary, which is also licensed under `GPL-3.0`.
