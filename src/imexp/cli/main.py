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


IOS_CONTACTS_REL = Path("31/31bb7ba8914766d4ba40d6dfb6113c8b614be442")
CONTACTS_FILE = "contacts.json"
HISTORY_FILE = "history.json"


@dataclass(frozen=True)
class DateRange:
    """Start/end date range for exports."""

    start: dt.datetime
    end: dt.datetime | None


@dataclass(frozen=True)
class ExportOptions:
    """CLI options that affect exporter behavior."""

    platform: str
    db_path: str
    conv_filter: str
    use_caller_id: bool
    copy_method: str
    output_format: str


@dataclass(frozen=True)
class PathsConfig:
    """Filesystem paths used by the CLI."""

    export_path: Path
    contacts_json: Path
    history_json: Path


@dataclass(frozen=True)
class UserLabels:
    """User label settings for post-processing."""

    me_label: str | None
    my_numbers: list[str]


@dataclass(frozen=True)
class RunConfig:
    """Resolved settings for an export run."""

    options: ExportOptions
    dates: DateRange
    paths: PathsConfig
    labels: UserLabels


@dataclass(frozen=True)
class PostprocessContext:
    """Inputs for post-processing exported files."""

    export_dir: Path
    contacts_map: dict[str, str]
    overrides: dict[str, str]
    labels: UserLabels


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


def run(cmd: list[str]) -> int:
    """Run a subprocess command and return the exit code."""
    logger = get_logger()
    logger.info("Running:")
    logger.info("  %s", " ".join(cmd))
    return subprocess.call(cmd)


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
        try:
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
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
    backups.sort(key=lambda b: b["last_backup"] or dt.datetime.min, reverse=True)
    return backups


def pick_ios_backup() -> Path:
    """Prompt to choose an iOS backup folder."""
    backups = list_ios_backups(config.IOS_BACKUP_ROOT)
    if not backups:
        eprint(f"No iOS backups found in {config.IOS_BACKUP_ROOT}")
        sys.exit(1)
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
    try:
        return json.loads(history_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_history(history_path: Path, history: dict) -> None:
    """Persist export history to disk."""
    history_path.write_text(json.dumps(history, indent=2, sort_keys=True))


def normalize_email(email: str) -> str:
    """Normalize emails for matching."""
    return email.strip().strip("<>").lower()


def phone_keys(raw: str) -> list[str]:
    """Generate normalized lookup keys for a phone number."""
    if "urn:" in raw:
        return []
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return []
    keys = [digits, f"+{digits}"]
    if digits.startswith("1") and len(digits) == 11:
        last10 = digits[-10:]
        keys.extend([last10, f"+{last10}"])
    return keys


def load_contacts_from_macos() -> dict[str, str]:
    """Load contacts from the macOS AddressBook database."""
    base = Path("~/Library/Application Support/AddressBook").expanduser()
    sources = list(base.glob("Sources/*/AddressBook-v22.abcddb"))
    if (base / "AddressBook-v22.abcddb").exists():
        sources.append(base / "AddressBook-v22.abcddb")
    mapping: dict[str, str] = {}
    for db in sources:
        try:
            conn = sqlite3.connect(db)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT r.ZFIRSTNAME, r.ZLASTNAME, p.ZFULLNUMBER, e.ZADDRESSNORMALIZED
                FROM ZABCDRECORD AS r
                LEFT JOIN ZABCDPHONENUMBER AS p ON r.Z_PK = p.ZOWNER
                LEFT JOIN ZABCDEMAILADDRESS AS e ON r.Z_PK = e.ZOWNER
                """
            )
            for first, last, phone, email in cur.fetchall():
                name_parts = [p for p in [first, last] if p]
                name = " ".join(name_parts).strip()
                if not name:
                    continue
                if email:
                    mapping[normalize_email(email)] = name
                if phone:
                    for key in phone_keys(phone):
                        mapping[key] = name
        except sqlite3.Error:
            continue
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass
    return mapping


def load_contacts_from_ios_backup(backup_root: Path) -> dict[str, str]:
    """Load contacts from an iOS backup database."""
    contacts_db = backup_root / IOS_CONTACTS_REL
    if not contacts_db.exists():
        return {}
    mapping: dict[str, str] = {}
    try:
        conn = sqlite3.connect(contacts_db)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT c0First, c1Last, c16Phone, c17Email
            FROM ABPersonFullTextSearch_content
            """
        )
        for first, last, phones, emails in cur.fetchall():
            name_parts = [p for p in [first, last] if p]
            name = " ".join(name_parts).strip()
            if not name:
                continue
            if emails:
                for token in str(emails).split():
                    mapping[normalize_email(token)] = name
            if phones:
                for token in str(phones).split():
                    for key in phone_keys(token):
                        mapping[key] = name
    except sqlite3.Error:
        return mapping
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    return mapping


def load_contacts_json(path: Path) -> dict:
    """Load persisted overrides from JSON."""
    if not path.exists():
        return {"overrides": {}}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"overrides": {}}


def save_contacts_json(path: Path, data: dict) -> None:
    """Persist overrides to JSON."""
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


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
    extra_numbers: list[str],
    me_label: str | None,
) -> dict[str, str]:
    """Combine contact data with overrides into a replacement map."""
    repl = {}
    for key, value in contacts_map.items():
        repl[key] = value
    for key, value in overrides.items():
        repl[key] = value
    if me_label:
        for num in extra_numbers:
            for key in phone_keys(num):
                repl[key] = me_label
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
    txt_files = list(context.export_dir.glob("*.txt"))
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

    replacements = build_replacements(
        context.overrides,
        context.contacts_map,
        context.labels.my_numbers,
        context.labels.me_label,
    )
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


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Interactive wrapper for imessage-exporter")
    parser.add_argument("--platform", choices=["macOS", "iOS"], help="Source platform")
    parser.add_argument("--db-path", help="Path to macOS chat.db or iOS backup root")
    parser.add_argument("--format", default="txt", choices=["txt", "html"])
    parser.add_argument(
        "--copy-method", default="full", choices=["disabled", "clone", "basic", "full"]
    )
    parser.add_argument("--start-date", help="Start date (natural language)")
    parser.add_argument("--end-date", help="End date (natural language)")
    parser.add_argument("--use-caller-id", action="store_true")
    parser.add_argument("--conversation-filter", help="Comma-separated filter string")
    parser.add_argument("--export-path", help="Output directory")
    parser.add_argument("--contacts-json", help="Path to contacts overrides JSON")
    parser.add_argument("--history-json", help="Path to history JSON")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def resolve_contacts_path(export_base: Path, args: argparse.Namespace) -> Path:
    """Resolve the contacts JSON path from args or defaults."""
    return Path(args.contacts_json or export_base / CONTACTS_FILE)


def resolve_history_path(export_base: Path, args: argparse.Namespace) -> Path:
    """Resolve the history JSON path from args or defaults."""
    return Path(args.history_json or export_base / HISTORY_FILE)


def resolve_platform_and_db() -> tuple[str, str]:
    """Prompt for platform and db path when interactive."""
    platform = prompt("Platform (macOS/iOS)", default="macOS")
    platform = "iOS" if platform.lower().startswith("i") else "macOS"
    if platform == "iOS":
        backup_root = pick_ios_backup()
        return platform, str(backup_root)
    return platform, ""


def resolve_date_range(last_end_dt: dt.datetime | None) -> DateRange:
    """Resolve start and end dates for interactive runs."""
    default_start = last_end_dt.strftime("%Y-%m-%d") if last_end_dt else ""
    start_text = prompt("Start date (natural language)", default=default_start)
    start_dt = parse_date(start_text) or dt.datetime.now()

    end_text = prompt("End date (natural language, enter for now)", default="now")
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


def resolve_user_labels() -> UserLabels:
    """Prompt for user labels and numbers."""
    me_label = prompt("Label for your own number (enter to skip)", default="").strip()
    my_numbers_raw = prompt("Your phone numbers (comma-separated, enter to skip)", default="")
    my_numbers = [n.strip() for n in my_numbers_raw.split(",") if n.strip()]
    return UserLabels(me_label=me_label or None, my_numbers=my_numbers)


def collect_inputs_interactive(
    export_base: Path,
    history: dict,
    contacts_path: Path,
    history_path: Path,
) -> RunConfig:
    """Collect inputs for interactive runs."""
    last_end = history.get("last_end")
    last_end_dt = parse_date(last_end) if last_end else None

    platform, db_path = resolve_platform_and_db()
    dates = resolve_date_range(last_end_dt)

    conv_filter = prompt("Conversation filter (comma-separated, enter to skip)", default="")
    use_caller_id = yes_no("Use caller ID instead of Me", default=True)

    options = ExportOptions(
        platform=platform,
        db_path=db_path,
        conv_filter=conv_filter,
        use_caller_id=use_caller_id,
        copy_method="full",
        output_format="txt",
    )
    paths = PathsConfig(
        export_path=resolve_output_path(export_base),
        contacts_json=contacts_path,
        history_json=history_path,
    )
    labels = resolve_user_labels()

    return RunConfig(options=options, dates=dates, paths=paths, labels=labels)


def collect_inputs_cli(
    args: argparse.Namespace,
    export_base: Path,
    history_path: Path,
    contacts_path: Path,
) -> RunConfig:
    """Collect inputs for non-interactive runs."""
    options = ExportOptions(
        platform=args.platform or "macOS",
        db_path=args.db_path or "",
        conv_filter=args.conversation_filter or "",
        use_caller_id=args.use_caller_id,
        copy_method=args.copy_method,
        output_format=args.format,
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
    labels = UserLabels(me_label=None, my_numbers=[])

    return RunConfig(options=options, dates=dates, paths=paths, labels=labels)


def build_export_command(config_run: RunConfig) -> list[str]:
    """Build the imessage-exporter command."""
    cmd = [
        "imessage-exporter",
        "--format",
        config_run.options.output_format,
        "--copy-method",
        config_run.options.copy_method,
        "--start-date",
        date_to_cli(config_run.dates.start),
        "--export-path",
        str(config_run.paths.export_path),
    ]

    if config_run.options.platform == "iOS":
        db_path = config_run.options.db_path or str(pick_ios_backup())
        cmd += ["--platform", "iOS", "--db-path", db_path]
    if config_run.options.conv_filter:
        cmd += ["--conversation-filter", config_run.options.conv_filter]
    if config_run.options.use_caller_id:
        cmd += ["--use-caller-id"]
    if config_run.dates.end:
        cmd += ["--end-date", date_to_cli(config_run.dates.end)]

    return cmd


def run_exporter(config_run: RunConfig) -> int:
    """Run imessage-exporter with the resolved config."""
    cmd = build_export_command(config_run)
    return run(cmd)


def load_contacts_for_platform(config_run: RunConfig) -> dict[str, str]:
    """Load contacts based on selected platform."""
    if config_run.options.platform == "iOS":
        return load_contacts_from_ios_backup(Path(config_run.options.db_path))
    return load_contacts_from_macos()


def ensure_export_dir(path: Path) -> None:
    """Ensure the export directory exists."""
    path.mkdir(parents=True, exist_ok=True)


def update_history_end(history: dict, end_dt: dt.datetime | None) -> None:
    """Update history with the latest end date."""
    history["last_end"] = end_dt.isoformat(sep=" ") if isinstance(end_dt, dt.datetime) else ""


def main() -> int:
    """Run the CLI entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)

    if not shutil.which("imessage-exporter"):
        eprint("imessage-exporter not found in PATH.")
        return 1

    export_base = config.base_output_dir()
    ensure_export_dir(export_base)

    history_path = resolve_history_path(export_base, args)
    contacts_path = resolve_contacts_path(export_base, args)
    history = load_history(history_path)

    interactive = not args.non_interactive and len(sys.argv) == 1
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

    rc = run_exporter(config_run)
    if rc != 0:
        return rc

    contacts_json = load_contacts_json(config_run.paths.contacts_json)
    overrides = contacts_json.get("overrides", {})

    contacts_map = load_contacts_for_platform(config_run)

    postprocess_exports(
        PostprocessContext(
            export_dir=config_run.paths.export_path,
            contacts_map=contacts_map,
            overrides=overrides,
            labels=config_run.labels,
        )
    )

    contacts_json["overrides"] = overrides
    save_contacts_json(config_run.paths.contacts_json, contacts_json)

    update_history_end(history, config_run.dates.end)
    save_history(config_run.paths.history_json, history)

    eprint(f"Export complete: {config_run.paths.export_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
