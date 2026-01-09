#!/usr/bin/env python3
import re
import sys
import json
import shutil
import sqlite3
import plistlib
import argparse
import subprocess
import datetime as dt
from pathlib import Path

try:
    import dateparser  # type: ignore
except Exception:  # pragma: no cover - user runtime only
    dateparser = None


IOS_BACKUP_ROOT = Path("~/Library/Application Support/MobileSync/Backup").expanduser()
IOS_CONTACTS_REL = Path("31/31bb7ba8914766d4ba40d6dfb6113c8b614be442")
BASE_OUTPUT_DIR = Path("./data/messages/sms")
CONTACTS_FILE = "contacts.json"
HISTORY_FILE = "history.json"


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def require_dateparser() -> None:
    if dateparser is None:
        eprint("Missing dependency: dateparser")
        eprint("Install with: pip install dateparser")
        sys.exit(2)


def run(cmd: list[str]) -> int:
    eprint("Running:")
    eprint("  " + " ".join(cmd))
    return subprocess.call(cmd)


def prompt(text: str, default: str | None = None) -> str:
    if default:
        prompt_text = f"{text} [{default}]: "
    else:
        prompt_text = f"{text}: "
    val = input(prompt_text).strip()
    return val if val else (default or "")


def yes_no(text: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    val = input(f"{text} ({hint}): ").strip().lower()
    if not val:
        return default
    return val in {"y", "yes"}


def sanitize_label(label: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip())
    return safe.strip("-") or "export"


def list_ios_backups(root: Path) -> list[dict]:
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
        except Exception:
            continue
    backups.sort(key=lambda b: b["last_backup"] or dt.datetime.min, reverse=True)
    return backups


def pick_ios_backup() -> Path:
    backups = list_ios_backups(IOS_BACKUP_ROOT)
    if not backups:
        eprint(f"No iOS backups found in {IOS_BACKUP_ROOT}")
        sys.exit(1)
    eprint("Detected iOS backups:")
    for i, b in enumerate(backups, start=1):
        last = b["last_backup"]
        last_s = last.isoformat(sep=" ") if isinstance(last, dt.datetime) else "Unknown"
        eprint(f"  {i}) {b['device_name']} (iOS {b['product_version']}) - {last_s}")
    choice = prompt("Select backup", default="1")
    try:
        idx = max(1, min(len(backups), int(choice)))
    except ValueError:
        idx = 1
    return backups[idx - 1]["path"]


def parse_date(text: str) -> dt.datetime | None:
    require_dateparser()
    if not text:
        return None
    return dateparser.parse(
        text,
        settings={"RELATIVE_BASE": dt.datetime.now(), "RETURN_AS_TIMEZONE_AWARE": False},
    )


def date_to_cli(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%d")


def load_history(base_dir: Path) -> dict:
    history_path = base_dir / HISTORY_FILE
    if not history_path.exists():
        return {}
    try:
        return json.loads(history_path.read_text())
    except Exception:
        return {}


def save_history(base_dir: Path, history: dict) -> None:
    history_path = base_dir / HISTORY_FILE
    history_path.write_text(json.dumps(history, indent=2, sort_keys=True))


def normalize_email(email: str) -> str:
    return email.strip().strip("<>").lower()


def phone_keys(raw: str) -> list[str]:
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
        except Exception:
            continue
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return mapping


def load_contacts_from_ios_backup(backup_root: Path) -> dict[str, str]:
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
    except Exception:
        return mapping
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return mapping


def load_contacts_json(path: Path) -> dict:
    if not path.exists():
        return {"overrides": {}}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"overrides": {}}


def save_contacts_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def extract_tokens_from_filename(name: str) -> set[str]:
    tokens = set()
    tokens.update(re.findall(r"\+?\d{7,15}", name))
    tokens.update(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", name))
    return tokens


def build_replacements(
    overrides: dict[str, str],
    contacts_map: dict[str, str],
    extra_numbers: list[str],
    me_label: str | None,
) -> dict[str, str]:
    repl = {}
    for k, v in contacts_map.items():
        repl[k] = v
    for k, v in overrides.items():
        repl[k] = v
    if me_label:
        for num in extra_numbers:
            for key in phone_keys(num):
                repl[key] = me_label
    return repl


def replace_in_text(text: str, key: str, value: str) -> str:
    if "@" in key:
        pattern = re.compile(re.escape(key), re.IGNORECASE)
        return pattern.sub(value, text)
    if re.fullmatch(r"\+?\d+", key):
        pattern = re.compile(rf"(?<!\d){re.escape(key)}(?!\d)")
        return pattern.sub(value, text)
    return text.replace(key, value)


def postprocess_exports(
    export_dir: Path,
    contacts_map: dict[str, str],
    overrides: dict[str, str],
    me_label: str | None,
    my_numbers: list[str],
    ask_for_missing: bool = True,
) -> None:
    txt_files = list(export_dir.glob("*.txt"))
    if not txt_files:
        return

    unknown_tokens = set()
    for f in txt_files:
        unknown_tokens |= extract_tokens_from_filename(f.name)
    known_keys = set(contacts_map.keys()) | set(overrides.keys())
    if ask_for_missing:
        for token in sorted(unknown_tokens):
            if token in known_keys:
                continue
            if "@" in token or re.fullmatch(r"\+?\d{7,15}", token):
                name = prompt(f"Name for {token} (enter to skip)", default="")
                if name:
                    overrides[token] = name

    replacements = build_replacements(overrides, contacts_map, my_numbers, me_label)
    if not replacements:
        return

    # Replace content and filenames
    keys = sorted(replacements.keys(), key=len, reverse=True)
    for f in txt_files:
        text = f.read_text(errors="ignore")
        for key in keys:
            text = replace_in_text(text, key, replacements[key])
        f.write_text(text)

    for f in txt_files:
        new_name = f.name
        for key in keys:
            new_name = replace_in_text(new_name, key, replacements[key])
        if new_name != f.name:
            f.rename(f.with_name(new_name))


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Interactive wrapper for imessage-exporter")
    p.add_argument("--platform", choices=["macOS", "iOS"], help="Source platform")
    p.add_argument("--db-path", help="Path to macOS chat.db or iOS backup root")
    p.add_argument("--format", default="txt", choices=["txt", "html"])
    p.add_argument("--copy-method", default="full", choices=["disabled", "clone", "basic", "full"])
    p.add_argument("--start-date", help="Start date (natural language)")
    p.add_argument("--end-date", help="End date (natural language)")
    p.add_argument("--use-caller-id", action="store_true")
    p.add_argument("--conversation-filter", help="Comma-separated filter string")
    p.add_argument("--export-path", help="Output directory")
    p.add_argument("--non-interactive", action="store_true")
    return p


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if not shutil.which("imessage-exporter"):
        eprint("imessage-exporter not found in PATH.")
        return 1

    interactive = not args.non_interactive and len(sys.argv) == 1

    base_output = BASE_OUTPUT_DIR
    base_output.mkdir(parents=True, exist_ok=True)

    history = load_history(base_output)
    last_end = history.get("last_end")
    last_end_dt = parse_date(last_end) if last_end else None

    if interactive:
        platform = prompt("Platform (macOS/iOS)", default="macOS")
        platform = "iOS" if platform.lower().startswith("i") else "macOS"
        if platform == "iOS":
            backup_root = pick_ios_backup()
            db_path = str(backup_root)
        else:
            db_path = ""

        default_start = ""
        if last_end_dt:
            default_start = last_end_dt.strftime("%Y-%m-%d")
        start_text = prompt("Start date (natural language)", default=default_start)
        start_dt = parse_date(start_text) or dt.datetime.now()

        end_text = prompt("End date (natural language, enter for now)", default="now")
        end_dt = parse_date(end_text) or dt.datetime.now()

        conv_filter = prompt("Conversation filter (comma-separated, enter to skip)", default="")
        use_caller_id = yes_no("Use caller ID instead of Me", default=True)
        copy_method = "full"

        label = prompt("Output label (enter for timestamp)", default="")
        if label:
            subdir = sanitize_label(label)
        else:
            subdir = dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        export_path = base_output / subdir

        me_label = prompt("Label for your own number (enter to skip)", default="").strip()
        my_numbers_raw = prompt("Your phone numbers (comma-separated, enter to skip)", default="")
        my_numbers = [n.strip() for n in my_numbers_raw.split(",") if n.strip()]
    else:
        platform = args.platform or "macOS"
        db_path = args.db_path or ""
        start_dt = parse_date(args.start_date or "") or dt.datetime.now()
        end_dt = parse_date(args.end_date or "") or dt.datetime.now()
        conv_filter = args.conversation_filter or ""
        use_caller_id = args.use_caller_id
        copy_method = args.copy_method
        export_path = Path(args.export_path or base_output / dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"))
        me_label = None
        my_numbers = []

    cmd = [
        "imessage-exporter",
        "--format",
        args.format,
        "--copy-method",
        copy_method,
        "--start-date",
        date_to_cli(start_dt),
        "--export-path",
        str(export_path),
    ]

    if platform == "iOS":
        cmd += ["--platform", "iOS", "--db-path", db_path or str(pick_ios_backup())]
    if conv_filter:
        cmd += ["--conversation-filter", conv_filter]
    if use_caller_id:
        cmd += ["--use-caller-id"]
    if end_dt:
        cmd += ["--end-date", date_to_cli(end_dt)]

    rc = run(cmd)
    if rc != 0:
        return rc

    contacts_json_path = base_output / CONTACTS_FILE
    contacts_json = load_contacts_json(contacts_json_path)
    overrides = contacts_json.get("overrides", {})

    if platform == "iOS":
        contacts_map = load_contacts_from_ios_backup(Path(db_path))
    else:
        contacts_map = load_contacts_from_macos()

    postprocess_exports(
        export_dir=Path(export_path),
        contacts_map=contacts_map,
        overrides=overrides,
        me_label=me_label,
        my_numbers=my_numbers,
    )

    contacts_json["overrides"] = overrides
    save_contacts_json(contacts_json_path, contacts_json)

    history["last_end"] = end_dt.isoformat(sep=" ") if isinstance(end_dt, dt.datetime) else ""
    save_history(base_output, history)

    eprint(f"Export complete: {export_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
