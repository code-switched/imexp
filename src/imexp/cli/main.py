"""CLI wrapper for imessage-exporter with contact post-processing."""

import re
import sys
import json
import shutil
import logging
import sqlite3
import plistlib
import argparse
import subprocess
import datetime as dt
from pathlib import Path
from dataclasses import dataclass

import dateparser

from imexp.cli import config
from imexp.cli.config import CLIConfig, ProfileConfig
from imexp.core.exporter_binary import resolve_exporter_binary
from imexp.core.utils.helpformatter import ColourHelpFormatter


IOS_CONTACTS_REL = Path("31/31bb7ba8914766d4ba40d6dfb6113c8b614be442")
IOS_MESSAGES_REL = Path("3d/3d0d7e5fb2ce288813306e4d4636395e047a3d28")
MACOS_MESSAGES_DB = Path("~/Library/Messages/chat.db").expanduser()
CONTACTS_FILE = "contacts.json"
HISTORY_FILE = "history.json"
EXPORT_META_FILE = "export_meta.json"
STAGING_DIR = ".staging"


@dataclass(frozen=True)
class DateRange:
    """Start/end date range for exports."""

    start: dt.datetime
    end: dt.datetime | None


@dataclass(frozen=True)
class ExportOptions:
    """CLI options that affect exporter behavior."""

    platform: str | None
    db_path: str | None
    conv_filter: str
    use_caller_id: bool
    copy_method: str
    output_format: str
    diagnostics: bool
    no_lazy: bool
    version: bool
    profile_name: str = ""


@dataclass(frozen=True)
class PathsConfig:
    """Filesystem paths used by the CLI."""

    export_path: Path
    contacts_json: Path
    history_json: Path


@dataclass(frozen=True)
class RunConfig:
    """Resolved settings for an export run."""

    options: ExportOptions
    dates: DateRange
    paths: PathsConfig


@dataclass(frozen=True)
class PostprocessContext:
    """Inputs for post-processing exported files."""

    export_dir: Path
    contacts_map: dict[str, str]
    overrides: dict[str, str]


@dataclass(frozen=True)
class ContactRecord:
    """Exact contact name and its canonical handles."""

    name: str
    handles: tuple[str, ...]


def get_logger() -> logging.Logger:
    """Return the module logger."""
    return logging.getLogger("imexp")


def configure_logging(verbose: bool) -> None:
    """Configure logging for console output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")


def eprint(msg: str) -> None:
    """Print to stderr."""
    print(msg, file=sys.stderr)


def run(cmd: list[str]) -> None:
    """Run a subprocess command."""
    logger = get_logger()
    logger.info("Running:")
    logger.info("  %s", " ".join(cmd))
    subprocess.check_call(cmd)


def prompt(text: str, default: str | None = None) -> str:
    """Prompt for input with an optional default."""
    if default:
        prompt_text = f"{text} [{default}]: "
    else:
        prompt_text = f"{text}: "
    val = input(prompt_text).strip()
    return val if val else (default or "")


def yes_no(text: str, default: bool = True) -> bool:
    """Prompt for a yes/no answer."""
    hint = "Y/n" if default else "y/N"
    val = input(f"{text} ({hint}): ").strip().lower()
    if not val:
        return default
    return val in {"y", "yes"}


def sanitize_label(label: str) -> str:
    """Convert a label to a filesystem-safe slug."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip())
    return safe.strip("-") or "export"


def list_ios_backups(root: Path) -> list[dict]:
    """Enumerate iOS backups and their metadata."""
    backups = []
    if not root.exists():
        return backups
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        info_path = entry / "Info.plist"
        if not info_path.exists():
            continue
        with info_path.open("rb") as f:
            info = plistlib.load(f)
        backups.append(
            {
                "path": entry,
                "device_name": info.get("Device Name", "Unknown"),
                "product_version": info.get("Product Version", "Unknown"),
                "last_backup": info.get("Last Backup Date"),
            }
        )
    backups.sort(key=lambda b: b["last_backup"] or dt.datetime.min, reverse=True)
    return backups


def pick_ios_backup() -> Path:
    """Prompt to choose an iOS backup folder."""
    backups = list_ios_backups(config.IOS_BACKUP_ROOT)
    if not backups:
        raise RuntimeError(f"No iOS backups found in {config.IOS_BACKUP_ROOT}")
    eprint("Detected iOS backups:")
    for i, backup in enumerate(backups, start=1):
        last = backup["last_backup"]
        last_s = last.isoformat(sep=" ") if isinstance(last, dt.datetime) else "Unknown"
        eprint(
            f"  {i}) {backup['device_name']} "
            f"(iOS {backup['product_version']}) - {last_s}"
        )
    choice = prompt("Select backup", default="1")
    try:
        idx = max(1, min(len(backups), int(choice)))
    except ValueError:
        idx = 1
    return backups[idx - 1]["path"]


def parse_date(text: str) -> dt.datetime | None:
    """Parse a natural language date string."""
    if not text:
        return None
    return dateparser.parse(
        text,
        settings={"RELATIVE_BASE": dt.datetime.now(), "RETURN_AS_TIMEZONE_AWARE": False},
    )


def date_to_cli(value: dt.datetime) -> str:
    """Format a date for CLI arguments."""
    return value.strftime("%Y-%m-%d")


def load_history(history_path: Path) -> dict:
    """Load export history from disk."""
    if not history_path.exists():
        return {}
    contents = history_path.read_text()
    if not contents.strip():
        return {}
    return json.loads(contents)


def save_history(history_path: Path, history: dict) -> None:
    """Persist export history to disk."""
    history_path.write_text(json.dumps(history, indent=2, sort_keys=True))


def dedupe_strings(values: list[str]) -> tuple[str, ...]:
    """Return unique strings in insertion order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def normalize_email(email: str) -> str:
    """Normalize emails for matching."""
    return email.strip().strip("<>").lower()


def looks_like_email(token: str) -> bool:
    """Return True when the token looks like an email address."""
    return "@" in token.strip()


def canonical_phone(raw: str) -> str | None:
    """Return the canonical phone representation for a token."""
    stripped = raw.strip()
    if not stripped:
        return None
    if "urn:" in stripped:
        return None

    digits = re.sub(r"\D", "", stripped)
    if not digits:
        return None

    if stripped.startswith("+"):
        return f"+{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    return digits


def canonical_handle(raw: str) -> str | None:
    """Return the canonical export handle for a token."""
    stripped = raw.strip().strip("<>")
    if not stripped:
        return None
    if looks_like_email(stripped):
        return normalize_email(stripped)

    phone = canonical_phone(stripped)
    if phone is not None:
        return phone

    return stripped.casefold()


def phone_keys(raw: str) -> list[str]:
    """Generate normalized lookup keys for a phone number."""
    if "urn:" in raw:
        return []
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return []
    keys = [digits, f"+{digits}"]
    if len(digits) == 10:
        keys.extend([f"1{digits}", f"+1{digits}"])
    if digits.startswith("1") and len(digits) == 11:
        last10 = digits[-10:]
        keys.extend([last10, f"+{last10}"])
    return keys


def handle_lookup_keys(raw: str) -> tuple[str, ...]:
    """Build the exact-match lookup keys for a handle token."""
    stripped = raw.strip().strip("<>")
    if not stripped:
        return ()
    if looks_like_email(stripped):
        return (normalize_email(stripped),)

    phone = canonical_phone(stripped)
    if phone is None:
        return (stripped.casefold(),)

    keys = phone_keys(phone)
    keys.append(phone)
    return dedupe_strings(keys)


def build_contact_name(first: str | None, last: str | None) -> str:
    """Build a display name from first/last parts."""
    name_parts = [part for part in (first, last) if part]
    return " ".join(name_parts).strip()


def build_contact_records(
    contact_names: dict[str, str],
    contact_handles: dict[str, set[str]],
) -> list[ContactRecord]:
    """Build deduplicated contact records from aggregated rows."""
    seen: set[tuple[str, tuple[str, ...]]] = set()
    records: list[ContactRecord] = []
    for key, name in contact_names.items():
        handles = tuple(sorted(contact_handles.get(key, set())))
        if not handles:
            continue

        dedupe_key = (name.casefold(), handles)
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        records.append(ContactRecord(name=name, handles=handles))
    records.sort(key=lambda record: (record.name.casefold(), record.handles))
    return records


def load_contact_records_from_macos() -> list[ContactRecord]:
    """Load exact contact records from macOS Contacts."""
    base = Path("~/Library/Application Support/AddressBook").expanduser()
    sources = list(base.glob("Sources/*/AddressBook-v22.abcddb"))
    if (base / "AddressBook-v22.abcddb").exists():
        sources.append(base / "AddressBook-v22.abcddb")

    contact_names: dict[str, str] = {}
    contact_handles: dict[str, set[str]] = {}
    for db in sources:
        with sqlite3.connect(db) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT r.Z_PK, r.ZFIRSTNAME, r.ZLASTNAME, p.ZFULLNUMBER, e.ZADDRESSNORMALIZED
                FROM ZABCDRECORD AS r
                LEFT JOIN ZABCDPHONENUMBER AS p ON r.Z_PK = p.ZOWNER
                LEFT JOIN ZABCDEMAILADDRESS AS e ON r.Z_PK = e.ZOWNER
                """
            )
            for record_id, first, last, phone, email in cur.fetchall():
                name = build_contact_name(first, last)
                if not name:
                    continue

                key = f"{db}:{record_id}"
                if key not in contact_names:
                    contact_names[key] = name
                    contact_handles[key] = set()

                for raw_handle in (phone, email):
                    handle = canonical_handle(str(raw_handle or ""))
                    if handle is None:
                        continue
                    contact_handles[key].add(handle)

    return build_contact_records(contact_names, contact_handles)


def load_contact_records_from_ios_backup(backup_root: Path) -> list[ContactRecord]:
    """Load exact contact records from an iOS backup."""
    contacts_db = backup_root / IOS_CONTACTS_REL
    if not contacts_db.exists():
        return []

    contact_names: dict[str, str] = {}
    contact_handles: dict[str, set[str]] = {}
    with sqlite3.connect(contacts_db) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT rowid, c0First, c1Last, c16Phone, c17Email
            FROM ABPersonFullTextSearch_content
            """
        )
        for record_id, first, last, phones, emails in cur.fetchall():
            name = build_contact_name(first, last)
            if not name:
                continue

            key = str(record_id)
            if key not in contact_names:
                contact_names[key] = name
                contact_handles[key] = set()

            for field in (phones, emails):
                for token in str(field or "").split():
                    handle = canonical_handle(token)
                    if handle is None:
                        continue
                    contact_handles[key].add(handle)

    return build_contact_records(contact_names, contact_handles)


def build_contacts_map(records: list[ContactRecord]) -> dict[str, str]:
    """Build the replacement lookup map from contact records."""
    mapping: dict[str, str] = {}
    for record in records:
        for handle in record.handles:
            for alias in handle_lookup_keys(handle):
                mapping[alias] = record.name
    return mapping


def load_contacts_from_macos() -> dict[str, str]:
    """Load contacts from the macOS AddressBook database."""
    return build_contacts_map(load_contact_records_from_macos())


def load_contacts_from_ios_backup(backup_root: Path) -> dict[str, str]:
    """Load contacts from an iOS backup database."""
    return build_contacts_map(load_contact_records_from_ios_backup(backup_root))


def load_contacts_json(path: Path) -> dict:
    """Load persisted overrides from JSON."""
    if not path.exists():
        return {"overrides": {}}
    contents = path.read_text()
    if not contents.strip():
        return {"overrides": {}}
    return json.loads(contents)


def save_contacts_json(path: Path, data: dict) -> None:
    """Persist overrides to JSON."""
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def load_contact_records_for_platform(
    platform: str | None,
    db_path: str | None,
) -> list[ContactRecord]:
    """Load exact contact records for the selected source platform."""
    if platform == "iOS":
        if not db_path:
            return []
        return load_contact_records_from_ios_backup(Path(db_path))

    return load_contact_records_from_macos()


def resolve_messages_db_path(platform: str | None, db_path: str | None) -> Path:
    """Resolve the message database path used for exact handle lookups."""
    if platform == "iOS":
        if not db_path:
            return IOS_MESSAGES_REL

        backup_root = Path(db_path).expanduser()
        if backup_root.is_file():
            return backup_root
        return backup_root / IOS_MESSAGES_REL

    if db_path:
        return Path(db_path).expanduser()

    return MACOS_MESSAGES_DB


def load_message_handles(platform: str | None, db_path: str | None) -> tuple[str, ...]:
    """Load exact handles from the messages database when available."""
    database_path = resolve_messages_db_path(platform, db_path)
    if not database_path.exists():
        return ()

    with sqlite3.connect(database_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id
            FROM handle
            WHERE id IS NOT NULL
              AND TRIM(id) != ''
            """
        )
        handles = [str(value).strip() for (value,) in cur.fetchall() if str(value).strip()]
    return tuple(sorted(set(handles)))


def build_handle_alias_index(handles: tuple[str, ...]) -> dict[str, set[str]]:
    """Map exact lookup aliases to canonical export handles."""
    index: dict[str, set[str]] = {}
    for handle in handles:
        for alias in handle_lookup_keys(handle):
            index.setdefault(alias, set()).add(handle)
    return index


def resolve_direct_handles(
    token: str,
    alias_index: dict[str, set[str]],
) -> tuple[str, ...]:
    """Resolve an exact handle token to one or more canonical export handles."""
    matched: list[str] = []
    for alias in handle_lookup_keys(token):
        matched.extend(sorted(alias_index.get(alias, set())))
    return dedupe_strings(matched)


def project_contact_handles(
    handles: tuple[str, ...],
    alias_index: dict[str, set[str]],
) -> tuple[str, ...]:
    """Project contact handles onto exact known handles when available."""
    projected: list[str] = []
    for handle in handles:
        direct_handles = resolve_direct_handles(handle, alias_index)
        if not direct_handles:
            continue
        projected.extend(direct_handles)
    return dedupe_strings(projected)


def exact_name_matches(
    token: str,
    contact_records: list[ContactRecord],
) -> list[ContactRecord]:
    """Return exact case-insensitive contact name matches for a token."""
    wanted = token.strip().casefold()
    return [record for record in contact_records if record.name.casefold() == wanted]


def format_contact_candidate(record: ContactRecord) -> str:
    """Format a contact record for ambiguity messages."""
    handles = ", ".join(record.handles)
    return f"{record.name} [{handles}]"


def resolve_filter_token(
    token: str,
    alias_index: dict[str, set[str]],
    contact_records: list[ContactRecord],
) -> tuple[str, ...]:
    """Resolve a single filter token to exact canonical export handles."""
    stripped = token.strip()
    if not stripped:
        raise ValueError("Conversation filter contains an empty token.")

    direct_handles = resolve_direct_handles(stripped, alias_index)
    if direct_handles:
        return direct_handles

    name_matches = exact_name_matches(stripped, contact_records)
    if len(name_matches) == 1:
        projected = project_contact_handles(name_matches[0].handles, alias_index)
        if projected:
            return projected
        raise ValueError(
            f"Selected filter `{stripped}` does not map to any known message handles."
        )

    if len(name_matches) > 1:
        candidates = "; ".join(format_contact_candidate(record) for record in name_matches)
        raise ValueError(
            f"Selected filter `{stripped}` matches multiple contacts. "
            f"Use an exact handle instead: {candidates}"
        )

    raise ValueError(
        f"Selected filter `{stripped}` does not exactly match any known handle or contact."
    )


def resolve_conversation_filter_strict(
    raw_filter: str,
    platform: str | None,
    db_path: str | None,
) -> str:
    """Resolve a raw conversation filter to exact canonical export handles."""
    if not raw_filter.strip():
        return ""

    contact_records = load_contact_records_for_platform(platform, db_path)
    alias_index = build_handle_alias_index(load_message_handles(platform, db_path))

    resolved_handles: list[str] = []
    for token in raw_filter.split(","):
        resolved_handles.extend(resolve_filter_token(token, alias_index, contact_records))

    return ",".join(dedupe_strings(resolved_handles))


def extract_tokens_from_filename(name: str) -> set[str]:
    """Extract phone numbers and emails from a filename."""
    stem = Path(name).stem
    tokens = set()
    tokens.update(re.findall(r"\+?\d{7,15}", stem))
    email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    for match in email_pattern.findall(stem):
        if "_" in match:
            for part in match.split("_"):
                if email_pattern.fullmatch(part):
                    tokens.add(part)
        else:
            tokens.add(match)
    return tokens


def build_replacements(
    overrides: dict[str, str],
    contacts_map: dict[str, str],
) -> dict[str, str]:
    """Combine contact data with overrides into a replacement map."""
    repl = {}
    for key, value in contacts_map.items():
        repl[key] = value
    for key, value in overrides.items():
        repl[key] = value
    return repl


def replace_in_text(text: str, key: str, value: str) -> str:
    """Replace a key with a value in arbitrary text."""
    if "@" in key:
        pattern = re.compile(re.escape(key), re.IGNORECASE)
        return pattern.sub(value, text)
    if re.fullmatch(r"\+?\d+", key):
        pattern = re.compile(rf"(?<!\d){re.escape(key)}(?!\d)")
        return pattern.sub(value, text)
    return text.replace(key, value)


def postprocess_exports(context: PostprocessContext, ask_for_missing: bool = True) -> None:
    """Rewrite export files and names using contact data."""
    txt_files = list(context.export_dir.rglob("*.txt"))
    if not txt_files:
        return

    unknown_tokens = set()
    for file_path in txt_files:
        unknown_tokens |= extract_tokens_from_filename(file_path.name)
    known_keys = set(context.contacts_map.keys()) | set(context.overrides.keys())
    if ask_for_missing:
        for token in sorted(unknown_tokens):
            if token in known_keys:
                continue
            if "@" in token or re.fullmatch(r"\+?\d{7,15}", token):
                name = prompt(f"Name for {token} (enter to skip)", default="")
                if name:
                    context.overrides[token] = name

    replacements = build_replacements(context.overrides, context.contacts_map)
    if not replacements:
        return

    keys = sorted(replacements.keys(), key=len, reverse=True)
    for file_path in txt_files:
        text = file_path.read_text(errors="ignore")
        for key in keys:
            text = replace_in_text(text, key, replacements[key])
        file_path.write_text(text)

    for file_path in txt_files:
        new_name = file_path.name
        for key in keys:
            new_name = replace_in_text(new_name, key, replacements[key])
        if new_name != file_path.name:
            file_path.rename(file_path.with_name(new_name))


@dataclass(frozen=True)
class HelpDefaults:
    """Resolved defaults for help text rendering."""

    platform: str
    format: str
    copy_method: str
    conversation_filter: str
    profile: str
    use_caller_id: str
    output_dir: str


def resolve_help_defaults(cli_config: CLIConfig | None = None) -> HelpDefaults:
    """Resolve config-aware defaults for help output."""
    if not cli_config:
        return _fallback_help_defaults()

    exp = cli_config.export
    return HelpDefaults(
        platform=exp.platform or "prompt",
        format=exp.format,
        copy_method=exp.copy_method,
        conversation_filter=exp.conversation_filter or "none",
        profile=exp.default_profile or "none",
        use_caller_id="enabled" if exp.use_caller_id else "disabled",
        output_dir=exp.output_dir,
    )


def _fallback_help_defaults() -> HelpDefaults:
    """Return hardcoded defaults when config is unavailable."""
    return HelpDefaults(
        platform="prompt",
        format="txt",
        copy_method="full",
        conversation_filter="none",
        profile="none",
        use_caller_id="enabled",
        output_dir="./data/messages/sms",
    )


def _with_default(help_text: str, default_value: str) -> str:
    """Append a default value to help text."""
    return f"{help_text} (default: {default_value})"


def add_export_args(
    parser: argparse.ArgumentParser,
    help_defaults: HelpDefaults | None = None,
    with_defaults: bool = True,
) -> None:
    """Add export arguments to a parser."""
    defaults = help_defaults or _fallback_help_defaults()
    default_format = "txt" if with_defaults else argparse.SUPPRESS
    default_copy_method = "full" if with_defaults else argparse.SUPPRESS
    default_bool = False if with_defaults else argparse.SUPPRESS
    default_value = None if with_defaults else argparse.SUPPRESS

    parser.add_argument(
        "-p",
        "--platform",
        choices=["macOS", "iOS"],
        default=default_value,
        help=_with_default("Source platform", defaults.platform),
    )
    parser.add_argument(
        "-d",
        "--db-path",
        default=default_value,
        help="Path to macOS chat.db or iOS backup root",
    )
    parser.add_argument(
        "-f",
        "--format",
        default=default_format,
        choices=["txt", "html"],
        help=_with_default("Output format", defaults.format),
    )
    parser.add_argument(
        "-c",
        "--copy-method",
        default=default_copy_method,
        choices=["disabled", "clone", "basic", "full"],
        help=_with_default("Attachment copy method", defaults.copy_method),
    )
    parser.add_argument("-s", "--start-date", default=default_value, help="Start date (natural language)")
    parser.add_argument(
        "-e",
        "--end-date",
        default=default_value,
        help="End date (natural language, before this date)",
    )
    parser.add_argument(
        "-u",
        "--use-caller-id",
        action="store_true",
        default=default_bool,
        help=_with_default("Use caller ID instead of Me", defaults.use_caller_id),
    )
    selector_group = parser.add_mutually_exclusive_group()
    selector_group.add_argument(
        "-k",
        "--conversation-filter",
        default=default_value,
        help=_with_default("Comma-separated filter string", defaults.conversation_filter),
    )
    selector_group.add_argument(
        "--profile",
        default=default_value,
        help=_with_default("Saved profile name", defaults.profile),
    )
    selector_group.add_argument(
        "--wizard",
        action="store_true",
        default=default_bool,
        help="Force the interactive wizard even when a default profile exists",
    )
    parser.add_argument(
        "-o",
        "--export-path",
        default=default_value,
        help=_with_default("Output directory", defaults.output_dir),
    )
    parser.add_argument("-j", "--contacts-json", default=default_value, help="Path to contacts overrides JSON")
    parser.add_argument("-y", "--history-json", default=default_value, help="Path to history JSON")
    parser.add_argument("-g", "--diagnostics", action="store_true", default=default_bool)
    parser.add_argument("-l", "--no-lazy", action="store_true", default=default_bool)
    parser.add_argument(
        "-r",
        "--version",
        action="store_true",
        default=default_bool,
        help="Show exporter version",
    )
    parser.add_argument(
        "-w",
        "--snapshot",
        action="store_true",
        default=default_bool,
        help="Create a new timestamped export instead of updating an existing one",
    )
    parser.add_argument("-n", "--non-interactive", action="store_true", default=default_bool)
    parser.add_argument("-v", "--verbose", action="store_true", default=default_bool)


def build_export_parser(
    subparsers: argparse._SubParsersAction,
    help_defaults: HelpDefaults | None = None,
) -> argparse.ArgumentParser:
    """Register the export subcommand parser."""
    parser = subparsers.add_parser(
        "export",
        help="Export messages via imessage-exporter",
        formatter_class=ColourHelpFormatter,
    )
    add_export_args(parser, help_defaults=help_defaults)
    parser.set_defaults(command="export")
    return parser

def add_relabel_args(parser: argparse.ArgumentParser) -> None:
    """Add relabel arguments to a parser."""
    parser.add_argument("-p", "--platform", choices=["macOS", "iOS"], help="Source platform")
    parser.add_argument("-d", "--db-path", help="Path to macOS chat.db or iOS backup root")
    parser.add_argument("-o", "--export-path", help="Export directory to relabel")
    parser.add_argument("-j", "--contacts-json", help="Path to contacts overrides JSON")
    parser.add_argument("-y", "--history-json", help="Path to history JSON")
    parser.add_argument(
        "-s",
        "--contacts-only",
        action="store_true",
        help="Use contacts.json only and skip prompts",
    )
    parser.add_argument("-n", "--non-interactive", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")


def build_relabel_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the relabel subcommand parser."""
    parser = subparsers.add_parser(
        "relabel",
        help="Relabel existing exports",
        formatter_class=ColourHelpFormatter,
    )
    add_relabel_args(parser)
    parser.set_defaults(command="relabel")
    return parser


def build_root_parser(help_defaults: HelpDefaults | None = None) -> argparse.ArgumentParser:
    """Build the root CLI parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="imexp CLI",
        formatter_class=ColourHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")
    build_export_parser(subparsers, help_defaults=help_defaults)
    build_relabel_parser(subparsers)
    return parser


def build_export_fallback_parser(
    help_defaults: HelpDefaults | None = None,
) -> argparse.ArgumentParser:
    """Build a parser for implicit export defaults."""
    parser = argparse.ArgumentParser(add_help=False)
    add_export_args(parser, help_defaults=help_defaults)
    parser.set_defaults(command="export", snapshot=False)
    return parser


def build_export_presence_parser() -> argparse.ArgumentParser:
    """Build a parser that records only explicitly provided export options."""
    parser = argparse.ArgumentParser(add_help=False)
    add_export_args(parser, with_defaults=False)
    return parser


def resolve_contacts_path(export_base: Path, args: argparse.Namespace) -> Path:
    """Resolve the contacts JSON path from args or defaults."""
    return Path(args.contacts_json or export_base / CONTACTS_FILE)


def resolve_history_path(export_base: Path, args: argparse.Namespace) -> Path:
    """Resolve the history JSON path from args or defaults."""
    return Path(args.history_json or export_base / HISTORY_FILE)


def resolve_platform_and_db(
    platform: str | None, db_path: str | None, interactive: bool
) -> tuple[str | None, str | None]:
    """Resolve platform and db path."""
    if platform:
        selected = "iOS" if platform.lower().startswith("i") else "macOS"
        if selected == "iOS":
            if not db_path and not interactive:
                raise ValueError("iOS platform requires --db-path in non-interactive mode.")
            if not db_path:
                backup_root = pick_ios_backup()
                return selected, str(backup_root)
            return selected, db_path
        return selected, ""

    if not interactive:
        return None, db_path

    platform = prompt("Platform (macOS/iOS)", default="macOS")
    selected = "iOS" if platform.lower().startswith("i") else "macOS"
    if selected == "iOS":
        backup_root = pick_ios_backup()
        return selected, str(backup_root)
    return selected, ""


def resolve_date_range(last_end_dt: dt.datetime | None) -> DateRange:
    """Resolve start and end dates for interactive runs."""
    default_start = last_end_dt.strftime("%Y-%m-%d") if last_end_dt else ""
    start_text = prompt("Start date (natural language)", default=default_start)
    start_dt = parse_date(start_text) or dt.datetime.now()

    end_text = prompt("End date (natural language, before this date)", default="now")
    end_dt = parse_date(end_text) or dt.datetime.now()
    return DateRange(start=start_dt, end=end_dt)


def resolve_output_path(export_base: Path) -> Path:
    """Resolve the output directory for interactive runs."""
    label = prompt("Output label (enter for timestamp)", default="")
    if label:
        subdir = sanitize_label(label)
    else:
        subdir = dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    return export_base / subdir


def collect_inputs_interactive(
    export_base: Path,
    history: dict,
    contacts_path: Path,
    history_path: Path,
) -> RunConfig:
    """Collect inputs for interactive runs."""
    last_end = history.get("last_end")
    last_end_dt = parse_date(last_end) if last_end else None

    platform, db_path = resolve_platform_and_db(None, None, True)
    dates = resolve_date_range(last_end_dt)

    raw_filter = prompt("Conversation filter (comma-separated, enter to skip)", default="")
    conv_filter = resolve_conversation_filter_strict(raw_filter, platform, db_path)
    use_caller_id = yes_no("Use caller ID instead of Me", default=True)

    options = ExportOptions(
        platform=platform,
        db_path=db_path,
        conv_filter=conv_filter,
        use_caller_id=use_caller_id,
        copy_method="full",
        output_format="txt",
        diagnostics=False,
        no_lazy=False,
        version=False,
        profile_name="",
    )
    paths = PathsConfig(
        export_path=resolve_output_path(export_base),
        contacts_json=contacts_path,
        history_json=history_path,
    )

    return RunConfig(options=options, dates=dates, paths=paths)


def collect_inputs_cli(
    args: argparse.Namespace,
    export_base: Path,
    history_path: Path,
    contacts_path: Path,
) -> RunConfig:
    """Collect inputs for non-interactive runs."""
    platform, db_path = resolve_platform_and_db(args.platform, args.db_path, False)
    conv_filter = resolve_conversation_filter_strict(
        args.conversation_filter or "",
        platform,
        db_path,
    )
    options = ExportOptions(
        platform=platform,
        db_path=db_path,
        conv_filter=conv_filter,
        use_caller_id=args.use_caller_id,
        copy_method=args.copy_method,
        output_format=args.format,
        diagnostics=args.diagnostics,
        no_lazy=args.no_lazy,
        version=args.version,
        profile_name=args.profile or "",
    )
    dates = DateRange(
        start=parse_date(args.start_date or "") or dt.datetime.now(),
        end=parse_date(args.end_date or "") or dt.datetime.now(),
    )
    default_dir = export_base / dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    paths = PathsConfig(
        export_path=Path(args.export_path or default_dir),
        contacts_json=contacts_path,
        history_json=history_path,
    )
    return RunConfig(options=options, dates=dates, paths=paths)


def build_export_command(
    config_run: RunConfig,
    exporter_binary: str | Path = "imessage-exporter",
) -> list[str]:
    """Build the imessage-exporter command."""
    cmd = [
        str(exporter_binary),
        "--format",
        config_run.options.output_format,
        "--copy-method",
        config_run.options.copy_method,
        "--start-date",
        date_to_cli(config_run.dates.start),
        "--export-path",
        str(config_run.paths.export_path),
    ]

    if config_run.options.diagnostics:
        cmd.append("--diagnostics")
    if config_run.options.no_lazy:
        cmd.append("--no-lazy")
    if config_run.options.version:
        cmd.append("--version")

    if config_run.options.platform == "iOS":
        db_path = config_run.options.db_path or str(pick_ios_backup())
        cmd += ["--platform", "iOS", "--db-path", db_path]
    if config_run.options.platform is None and config_run.options.db_path:
        cmd += ["--db-path", config_run.options.db_path]
    if config_run.options.conv_filter:
        cmd += ["--conversation-filter", config_run.options.conv_filter]
    if config_run.options.use_caller_id:
        cmd += ["--use-caller-id"]
    if config_run.dates.end:
        cmd += ["--end-date", date_to_cli(config_run.dates.end)]

    return cmd


def run_exporter(config_run: RunConfig) -> None:
    """Run imessage-exporter with the resolved config."""
    cmd = build_export_command(config_run, exporter_binary=resolve_exporter_binary())
    run(cmd)


def warn_on_date_range(config_run: RunConfig) -> None:
    """Print a preflight summary for the date range."""
    start_s = date_to_cli(config_run.dates.start)
    if config_run.dates.end is None:
        eprint(f"Date range: {start_s} -> (before now)")
        return

    end_s = date_to_cli(config_run.dates.end)
    eprint(f"Date range: {start_s} -> (before {end_s})")
    if start_s == end_s:
        eprint("Warning: start and end are the same day; exports may be empty.")


def load_contacts_for_platform(platform: str, db_path: str) -> dict[str, str]:
    """Load contacts based on selected platform."""
    if platform == "iOS":
        return load_contacts_from_ios_backup(Path(db_path))
    return load_contacts_from_macos()


def ensure_export_dir(path: Path) -> None:
    """Ensure the export directory exists."""
    path.mkdir(parents=True, exist_ok=True)


def update_history_end(history: dict, end_dt: dt.datetime | None) -> None:
    """Update history with the latest end date."""
    history["last_end"] = end_dt.isoformat(sep=" ") if isinstance(end_dt, dt.datetime) else ""


def load_export_meta(export_dir: Path) -> dict:
    """Load per-export metadata from an export directory."""
    meta_path = export_dir / EXPORT_META_FILE
    if not meta_path.exists():
        return {}
    contents = meta_path.read_text()
    if not contents.strip():
        return {}
    return json.loads(contents)


def save_export_meta(export_dir: Path, meta: dict) -> None:
    """Persist per-export metadata to an export directory."""
    meta_path = export_dir / EXPORT_META_FILE
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))


def build_export_meta(config_run: RunConfig) -> dict:
    """Build metadata for the current export run."""
    return {
        "conv_filter": config_run.options.conv_filter,
        "profile": config_run.options.profile_name,
        "platform": config_run.options.platform or "",
        "last_end": (
            config_run.dates.end.isoformat(sep=" ")
            if isinstance(config_run.dates.end, dt.datetime)
            else ""
        ),
        "updated_at": dt.datetime.now().isoformat(sep=" "),
    }


def merge_text_files(staging_dir: Path, target_dir: Path) -> None:
    """Append new text content from staging into target."""
    for staged_file in staging_dir.glob("*.txt"):
        target_file = target_dir / staged_file.name
        staged_text = staged_file.read_text(errors="ignore")
        if not staged_text.strip():
            continue
        if not target_file.exists():
            target_file.write_text(staged_text)
            continue
        existing_text = target_file.read_text(errors="ignore")
        with target_file.open("a") as f:
            if existing_text and not existing_text.endswith("\n"):
                f.write("\n")
            f.write(staged_text)


def merge_attachments(staging_dir: Path, target_dir: Path) -> int:
    """Copy new attachment files from staging into target."""
    staged_attachments = staging_dir / "attachments"
    if not staged_attachments.exists():
        return 0
    target_attachments = target_dir / "attachments"
    target_attachments.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in staged_attachments.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(staged_attachments)
        dest = target_attachments / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    return copied


def merge_export_dirs(staging_dir: Path, target_dir: Path) -> None:
    """Merge a staged export into an existing target export."""
    logger = get_logger()
    target_dir.mkdir(parents=True, exist_ok=True)
    merge_text_files(staging_dir, target_dir)
    copied = merge_attachments(staging_dir, target_dir)
    logger.info("Merged %d new attachment(s) into %s", copied, target_dir)


def find_update_target(
    export_base: Path,
    conv_filter: str,
    profile_name: str = "",
) -> Path | None:
    """Auto-detect the existing export directory to update.

    Returns the matching directory or None if no suitable target is found.
    """
    candidates = list_recent_exports(export_base, limit=50)
    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    if profile_name:
        for path in candidates:
            meta = load_export_meta(path)
            if meta.get("profile", "") == profile_name:
                return path

    for path in candidates:
        meta = load_export_meta(path)
        if meta.get("conv_filter", "") == conv_filter:
            return path

    return None


def resolve_update_target(
    export_base: Path, args: argparse.Namespace, interactive: bool
) -> Path | None:
    """Resolve the target export directory for an update run.

    Returns the target directory, or None if no existing export is found
    (caller should bootstrap a new one).
    """
    if args.export_path:
        chosen = Path(args.export_path).expanduser()
        if not chosen.exists():
            raise FileNotFoundError(f"Update target not found: {chosen}")
        return chosen

    conv_filter = getattr(args, "conversation_filter", None) or ""
    profile_name = getattr(args, "profile", None) or ""
    target = find_update_target(export_base, conv_filter, profile_name=profile_name)
    if target:
        return target

    if interactive:
        recent = list_recent_exports(export_base, limit=3)
        if recent:
            eprint("No auto-detected target. Select one or press enter for new export:")
            for idx, path in enumerate(recent, start=1):
                eprint(f"  {idx}) {path}")
            selection = prompt("Select export or enter for new", default="")
            if selection.isdigit():
                idx = max(1, min(len(recent), int(selection)))
                return recent[idx - 1]

    return None


def staging_has_content(staging_dir: Path) -> bool:
    """Return True when the staging directory contains any files or directories."""
    if not staging_dir.exists():
        return False
    return any(staging_dir.iterdir())


def cleanup_staging_dir(staging_dir: Path) -> None:
    """Remove the staging run directory and its parent when empty."""
    if not staging_dir.exists():
        return

    shutil.rmtree(staging_dir)
    staging_root = staging_dir.parent
    if not staging_root.exists():
        return
    if any(staging_root.iterdir()):
        return
    staging_root.rmdir()


def run_update_export(
    config_run: RunConfig,
    target_dir: Path,
    export_base: Path,
    contacts_path: Path,
) -> None:
    """Run an incremental export and merge into an existing directory."""
    logger = get_logger()
    staging_dir = export_base / STAGING_DIR / dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    staging_dir.mkdir(parents=True, exist_ok=True)
    completed = False

    try:
        staging_config = RunConfig(
            options=config_run.options,
            dates=config_run.dates,
            paths=PathsConfig(
                export_path=staging_dir,
                contacts_json=config_run.paths.contacts_json,
                history_json=config_run.paths.history_json,
            ),
        )

        warn_on_date_range(staging_config)
        run_exporter(staging_config)

        contacts_json = load_contacts_json(contacts_path)
        overrides = contacts_json.get("overrides", {})
        contacts_map = load_contacts_for_platform(
            config_run.options.platform, config_run.options.db_path
        )
        postprocess_exports(
            PostprocessContext(
                export_dir=staging_dir,
                contacts_map=contacts_map,
                overrides=overrides,
            ),
            ask_for_missing=False,
        )
        contacts_json["overrides"] = overrides
        save_contacts_json(contacts_path, contacts_json)

        merge_export_dirs(staging_dir, target_dir)

        meta = load_export_meta(target_dir)
        meta.update(build_export_meta(config_run))
        save_export_meta(target_dir, meta)
        completed = True
    finally:
        if completed:
            cleanup_staging_dir(staging_dir)
            logger.info("Update complete: %s", target_dir)
            return

        if not staging_has_content(staging_dir):
            cleanup_staging_dir(staging_dir)
            return

        eprint(f"Update failed. Preserved staged files at: {staging_dir}")


def list_recent_exports(export_base: Path, limit: int = 3) -> list[Path]:
    """Return the most recent export directories."""
    if not export_base.exists():
        return []
    candidates = [
        path
        for path in export_base.iterdir()
        if path.is_dir() and path.name != STAGING_DIR
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[:limit]


def select_export_path(export_base: Path) -> Path:
    """Prompt to select a recent export directory."""
    recent = list_recent_exports(export_base, limit=3)
    if not recent:
        raise FileNotFoundError(f"No exports found under {export_base}")

    eprint("Recent exports:")
    for idx, path in enumerate(recent, start=1):
        eprint(f"  {idx}) {path}")
    selection = prompt("Select export (1-3) or enter path", default="1")
    if selection.isdigit():
        idx = max(1, min(len(recent), int(selection)))
        return recent[idx - 1]

    chosen = Path(selection).expanduser()
    if not chosen.exists():
        raise FileNotFoundError(f"Export path not found: {chosen}")
    return chosen


def resolve_relabel_paths(
    export_base: Path, args: argparse.Namespace, interactive: bool
) -> Path:
    """Resolve the export path for relabeling."""
    if args.export_path:
        chosen = Path(args.export_path).expanduser()
        if not chosen.exists():
            raise FileNotFoundError(f"Export path not found: {chosen}")
        return chosen

    if not interactive:
        raise ValueError("Relabeling requires --export-path in non-interactive mode.")

    return select_export_path(export_base)


def run_relabel(
    export_base: Path,
    contacts_path: Path,
    args: argparse.Namespace,
    interactive: bool,
) -> None:
    """Relabel an existing export directory."""
    export_path = resolve_relabel_paths(export_base, args, interactive)
    platform, db_path = resolve_platform_and_db(args.platform, args.db_path, interactive)

    contacts_json = load_contacts_json(contacts_path)
    overrides = contacts_json.get("overrides", {})
    contacts_map = load_contacts_for_platform(platform, db_path)

    postprocess_exports(
        PostprocessContext(
            export_dir=export_path,
            contacts_map=contacts_map,
            overrides=overrides,
        ),
        ask_for_missing=interactive and not args.contacts_only,
    )

    contacts_json["overrides"] = overrides
    save_contacts_json(contacts_path, contacts_json)
    eprint(f"Relabel complete: {export_path}")


def resolve_update_dates(
    args: argparse.Namespace, target_dir: Path, history: dict
) -> DateRange:
    """Resolve the date range for an update run.

    Prefers export_meta.json in the target dir, falls back to history.json,
    then to the CLI --start-date flag.
    """
    meta = load_export_meta(target_dir)
    meta_end = meta.get("last_end", "")
    history_end = history.get("last_end", "")

    start_text = getattr(args, "start_date", None) or ""
    if not start_text and meta_end:
        start_text = meta_end
    if not start_text and history_end:
        start_text = history_end
    if not start_text:
        raise ValueError(
            "Cannot determine start date for update. "
            "Provide --start-date or ensure the target has export_meta.json."
        )

    start_dt = parse_date(start_text)
    if not start_dt:
        raise ValueError(f"Could not parse start date: {start_text}")

    end_text = getattr(args, "end_date", None) or ""
    end_dt = parse_date(end_text) or dt.datetime.now()
    return DateRange(start=start_dt, end=end_dt)


def default_export_dir(export_base: Path, conv_filter: str, profile_name: str = "") -> Path:
    """Derive the default export directory name from the conversation filter."""
    if profile_name:
        return export_base / sanitize_label(profile_name)
    if conv_filter:
        return export_base / sanitize_label(conv_filter)
    return export_base / dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")


def bootstrap_export_dir(export_base: Path, conv_filter: str, profile_name: str = "") -> Path:
    """Create the initial export directory for a new continuous export."""
    export_dir = default_export_dir(export_base, conv_filter, profile_name=profile_name)
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def announce_profile(profile_name: str) -> None:
    """Print the selected profile before export starts."""
    if not profile_name:
        return
    eprint(f"Using profile: {profile_name}")


def run_continuous(
    args: argparse.Namespace,
    export_base: Path,
    contacts_path: Path,
    history_path: Path,
    history: dict,
    interactive: bool,
) -> None:
    """Orchestrate a continuous export: update existing or bootstrap new."""
    platform, db_path = resolve_platform_and_db(args.platform, args.db_path, interactive)
    conv_filter = resolve_conversation_filter_strict(
        args.conversation_filter or "",
        platform,
        db_path,
    )
    args.conversation_filter = conv_filter

    profile_name = args.profile or ""
    target_dir = resolve_update_target(export_base, args, interactive)
    if not target_dir:
        target_dir = bootstrap_export_dir(export_base, conv_filter, profile_name=profile_name)
        eprint(f"No existing export found. Creating: {target_dir}")

    meta = load_export_meta(target_dir)
    has_prior = bool(meta.get("last_end"))

    if has_prior:
        dates = resolve_update_dates(args, target_dir, history)
    else:
        start_dt = parse_date(getattr(args, "start_date", None) or "") or dt.datetime.now()
        end_dt = parse_date(getattr(args, "end_date", None) or "") or dt.datetime.now()
        dates = DateRange(start=start_dt, end=end_dt)

    options = ExportOptions(
        platform=platform,
        db_path=db_path,
        conv_filter=conv_filter,
        use_caller_id=args.use_caller_id,
        copy_method=args.copy_method,
        output_format=args.format,
        diagnostics=args.diagnostics,
        no_lazy=args.no_lazy,
        version=args.version,
        profile_name=profile_name,
    )
    config_run = RunConfig(
        options=options,
        dates=dates,
        paths=PathsConfig(
            export_path=target_dir,
            contacts_json=contacts_path,
            history_json=history_path,
        ),
    )

    announce_profile(profile_name)
    run_update_export(config_run, target_dir, export_base, contacts_path)

    update_history_end(history, dates.end)
    save_history(history_path, history)


def run_snapshot(
    args: argparse.Namespace,
    export_base: Path,
    contacts_path: Path,
    history_path: Path,
    history: dict,
    interactive: bool,
) -> None:
    """Run a snapshot export into a new timestamped directory."""
    if interactive:
        config_run = collect_inputs_interactive(
            export_base=export_base,
            history=history,
            contacts_path=contacts_path,
            history_path=history_path,
        )
    else:
        config_run = collect_inputs_cli(
            args=args,
            export_base=export_base,
            history_path=history_path,
            contacts_path=contacts_path,
        )

    announce_profile(config_run.options.profile_name)
    warn_on_date_range(config_run)
    run_exporter(config_run)

    contacts_json = load_contacts_json(config_run.paths.contacts_json)
    overrides = contacts_json.get("overrides", {})

    contacts_map = load_contacts_for_platform(
        config_run.options.platform, config_run.options.db_path
    )

    postprocess_exports(
        PostprocessContext(
            export_dir=config_run.paths.export_path,
            contacts_map=contacts_map,
            overrides=overrides,
        ),
        ask_for_missing=interactive,
    )

    contacts_json["overrides"] = overrides
    save_contacts_json(config_run.paths.contacts_json, contacts_json)

    meta = build_export_meta(config_run)
    save_export_meta(config_run.paths.export_path, meta)

    update_history_end(history, config_run.dates.end)
    save_history(config_run.paths.history_json, history)

    eprint(f"Export complete: {config_run.paths.export_path}")


def require_profile(cli_config: CLIConfig, name: str) -> ProfileConfig:
    """Return a configured profile or raise a clear error."""
    profile = cli_config.profiles.get(name)
    if not profile:
        raise ValueError(f"Unknown profile `{name}` in {cli_config.path}")
    if not profile.handles:
        raise ValueError(f"Profile `{name}` has no handles configured.")
    return profile


def resolve_selected_profile(
    args: argparse.Namespace,
    cli_config: CLIConfig,
    explicit_options: set[str],
) -> ProfileConfig | None:
    """Resolve the selected profile from CLI flags or config defaults."""
    if getattr(args, "wizard", False):
        return None
    if "profile" in explicit_options:
        return require_profile(cli_config, args.profile)
    if "conversation_filter" in explicit_options:
        return None
    if not cli_config.export.default_profile:
        return None
    return require_profile(cli_config, cli_config.export.default_profile)


def apply_profile_defaults(
    args: argparse.Namespace,
    profile: ProfileConfig,
    explicit_options: set[str],
) -> None:
    """Apply saved profile overrides to unresolved CLI arguments."""
    if "platform" not in explicit_options and profile.platform:
        args.platform = profile.platform
    if "format" not in explicit_options and profile.format:
        args.format = profile.format
    if "copy_method" not in explicit_options and profile.copy_method:
        args.copy_method = profile.copy_method
    if "use_caller_id" not in explicit_options and profile.use_caller_id is not None:
        args.use_caller_id = profile.use_caller_id
    if "conversation_filter" not in explicit_options:
        args.conversation_filter = ",".join(profile.handles)
    args.profile = profile.name


def apply_config_defaults(
    args: argparse.Namespace,
    cli_config: CLIConfig,
    explicit_options: set[str],
) -> ProfileConfig | None:
    """Apply config.ini defaults to args that weren't set on the command line."""
    exp = cli_config.export

    if "platform" not in explicit_options and exp.platform:
        args.platform = exp.platform

    if "use_caller_id" not in explicit_options and exp.use_caller_id:
        args.use_caller_id = True

    if "format" not in explicit_options and exp.format:
        args.format = exp.format

    if "copy_method" not in explicit_options and exp.copy_method:
        args.copy_method = exp.copy_method

    selected_profile = resolve_selected_profile(args, cli_config, explicit_options)
    if selected_profile:
        apply_profile_defaults(args, selected_profile, explicit_options)
        return selected_profile

    if "conversation_filter" not in explicit_options and exp.conversation_filter:
        args.conversation_filter = exp.conversation_filter

    return None


def should_run_export_wizard(
    raw_export_argv: list[str],
    args: argparse.Namespace,
    selected_profile: ProfileConfig | None,
) -> bool:
    """Return True when export should fall back to the interactive wizard."""
    if getattr(args, "non_interactive", False):
        return False
    if getattr(args, "wizard", False):
        return True
    if selected_profile is not None:
        return False
    return not raw_export_argv


def main() -> None:
    """Run the CLI entrypoint."""
    cli_config = config.load_config()
    help_defaults = resolve_help_defaults(cli_config)
    raw_argv = sys.argv[1:]

    parser = build_root_parser(help_defaults=help_defaults)
    args = parser.parse_args()
    command = args.command or "export"
    if args.command is None and len(sys.argv) > 1:
        args = parser.parse_args(["export", *sys.argv[1:]])
        command = "export"
    if args.command is None and len(sys.argv) == 1:
        args = build_export_fallback_parser(help_defaults=help_defaults).parse_args([])
        command = "export"

    configure_logging(args.verbose)
    raw_export_argv = raw_argv
    if raw_export_argv and raw_export_argv[0] == "export":
        raw_export_argv = raw_export_argv[1:]

    explicit_options: set[str] = set()
    if command == "export":
        presence_args = build_export_presence_parser().parse_args(raw_export_argv)
        explicit_options = set(vars(presence_args))

    selected_profile = apply_config_defaults(args, cli_config, explicit_options)

    export_base = config.base_output_dir(cli_config, profile=selected_profile)
    ensure_export_dir(export_base)

    contacts_path = resolve_contacts_path(export_base, args)
    interactive = command == "export" and should_run_export_wizard(
        raw_export_argv,
        args,
        selected_profile,
    )
    relabel_interactive = not args.non_interactive and command == "relabel"

    if command == "relabel":
        run_relabel(export_base, contacts_path, args, relabel_interactive)
        return

    resolve_exporter_binary()

    history_path = resolve_history_path(export_base, args)
    history = load_history(history_path)

    if getattr(args, "snapshot", False):
        run_snapshot(args, export_base, contacts_path, history_path, history, interactive)
        return

    run_continuous(args, export_base, contacts_path, history_path, history, interactive)


if __name__ == "__main__":
    raise SystemExit(main())
