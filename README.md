# imexp

An interactive CLI wrapper for [imessage-exporter](https://github.com/ReagentX/imessage-exporter) that adds contact name resolution and post-processing to your iMessage exports.

## Features

- **Interactive wizard** — run `imexp` with no arguments for a guided export experience
- **Natural language dates** — use phrases like "last 6 months" or "2 weeks ago"
- **Contact resolution** — automatically maps phone numbers and emails to names from your macOS or iOS Contacts database
- **iOS backup support** — auto-detects backups and lets you pick by device name/date
- **Post-processing** — renames exported files and replaces raw handles with contact names
- **Export history** — tracks your last export date to avoid duplicates

## Requirements

- macOS (required for Contacts database access)
- Python 3.12+
- [imessage-exporter](https://github.com/ReagentX/imessage-exporter) installed and in your PATH

## Installation

```bash
pip install imexp
```

Or install from source:

```bash
git clone https://github.com/code-switched/imexp.git
cd imexp
pip install -e .
```

## Usage

### Interactive mode

Simply run with no arguments for the guided wizard:

```bash
imexp
```

You'll be prompted for:
- Platform (macOS or iOS backup)
- Date range (natural language supported)
- Export location

### Command-line mode

```bash
imexp export --start-date "2024-01-01" --end-date "2024-06-01" --format txt
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

By default, files are stored in `./data/messages/sms/`:

- `contacts.json` — custom name overrides for unknown numbers
- `history.json` — tracks last export date

## License

MIT
