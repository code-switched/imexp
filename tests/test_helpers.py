"""Unit tests for CLI helpers."""

from imexp.cli import main as cli


def test_sanitize_label() -> None:
    """Sanitize labels into filesystem-safe strings."""
    assert cli.sanitize_label(" Hello, World! ") == "Hello-World"
    assert cli.sanitize_label("!!!") == "export"


def test_phone_keys() -> None:
    """Normalize phone numbers for matching."""
    assert not cli.phone_keys("urn:something")
    assert cli.phone_keys("(555) 123-4567") == ["5551234567", "+5551234567"]
    assert cli.phone_keys("+1 415-555-1212") == [
        "14155551212",
        "+14155551212",
        "4155551212",
        "+4155551212",
    ]


def test_replace_in_text_email_is_case_insensitive() -> None:
    """Replace emails in a case-insensitive way."""
    text = "Email ME at Test@Example.com"
    assert cli.replace_in_text(text, "test@example.com", "Alice") == "Email ME at Alice"


def test_extract_tokens_from_filename() -> None:
    """Extract phone and email tokens from filenames."""
    tokens = cli.extract_tokens_from_filename("chat_+14155551212_test@example.com.txt")
    assert "+14155551212" in tokens
    assert "test@example.com" in tokens
