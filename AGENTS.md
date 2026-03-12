# Agent Guide

Always check for a virtual environment first. Do not assume a virtual environment is activated. Use the venv when running commands.

if Unix:

- `./.venv/bin/python`
- `./.venv/bin/pip`
- `./.venv/bin/pylint`
- `./.venv/bin/pytest`

if Windows:

- `.\.venv\Scripts\python`
- `.\.venv\Scripts\pip`
- `.\.venv\Scripts\pylint`
- `.\.venv\Scripts\pytest`

Run pytest before and after each turn so you know if your work broke any logic.

Once we come to an agreement on what code should be committed craft a commit mesage for the new code based on ./docs/dev/commits.md and commit the code, make sure the body is a hyphenated bullet list. Do not push unless asked.

## Brainstorming

Ask me clarifying questions until you know what I want to build and walk me through the setup step by step.

## Syntax

Follow these rules when generating or modifying code in this repository:

- Use guard clauses to exit early. Keep the happy path straight and flat.
- Avoid deep nesting; split logic into small functions instead.
- Prefer multiple `if` statements over large `if/elif/else` pyramids.
- Use `else` sparingly and only when it clarifies binary logic.
- Avoid using try except blocks unless absolutely necessary.
- Catch only specific exceptions you expect and know how to handle.
- Do NOT use `except Exception:`
- If you catch broadly for logging, re-raise so errors aren’t swallowed.
- Keep functions focused on one responsibility with clear inputs/outputs.
- Fail fast when invariants are violated; use precise error messages.
- Prioritize clarity over cleverness, code should read top-to-bottom like a story.
- For CLI tools, use `Declarative` control flow style. Do NOT use exit-code style control flow. Let the entrypoint handle process termination.
- We are in the pre-alpha building stage, there is no need for fallbacks or backwards compatability. Cutover. This is unreleased, all code needs to be canonical.

(See below for full guidelines and examples.)

# AGENTS: Coding Style & Control-Flow Guidelines

This project prefers explicit, predictable control flow and narrow, intentional error handling.

The goals:

- Code that reads top-to-bottom like a story
- Minimal nesting and cognitive load
- If necessary, use exceptions and branches that reflect *specific, known* conditions

If you’re an agent writing or editing code here, follow the rules below.

---

## 1. Control Flow: Prefer Guard Clauses, Avoid Deep Nesting

### 1.1. Guard clauses over `else` pyramids

Use early returns (guard clauses) for invalid inputs, edge cases, and “nothing to do” states.

✅ Preferred:

```python
def process_item(item):
    if item is None:
        return None

    if not item.active:
        return None

    if item.value < 0:
        raise ValueError("value must be non-negative")

    return item.value * 2
```

❌ Avoid:

```python
def process_item(item):
    if item is not None:
        if item.active:
            if item.value >= 0:
                return item.value * 2
            else:
                raise ValueError("value must be non-negative")
        else:
            return None
    else:
        return None
```

Rules:

- Prefer a flat, linear “happy path”.
- Use multiple `if` guard clauses instead of a single `if/elif/else` tower when it improves clarity.
- `else:` is not banned, but avoid it when it hides which conditions actually lead there.

### 1.2. Keep functions small and focused

If you feel tempted to add multiple `else` branches or deeply nested conditionals:

- First try splitting logic into smaller functions.
- Each function should do one clear thing and return early when preconditions fail.

---

## 2. Exceptions: Be Specific, Avoid Catch-Alls

### 2.1. No `except Exception:` (almost always)

Do not use `except Exception:` or `except BaseException:` unless you are:

- Logging/cleaning up and then re-raising.

Rules:

- Catch only the specific exceptions you expect and know how to handle.
- If you don't know how to recover, don’t catch. Let it propagate.

### 2.2. Group related exceptions explicitly

If multiple known failure modes can be handled in the same way, catch them as a tuple.

### 2.3. Logging + re-raise instead of swallowing

If you need to observe unexpected exceptions, log and re-raise.

This is acceptable at boundaries or in “monitoring” code. The key is: don’t swallow.

---

## 3. Where Catch-Alls *Are* Allowed

There are a few places where a broad catch is acceptable and sometimes required.

### 3.1. Top-level entry points

Guidelines:

- Keep the handler small (log, cleanup, exit).
- Do not bury business logic inside such a handler.

### 3.2. Custom exception hierarchies

For libraries or complex modules, define a project-specific base exception.

✅ Preferred:

```python
class AppError(Exception): pass
class ConfigError(AppError): pass
class NetworkError(AppError): pass

def run_step():
    raise ConfigError("Missing token")
```

Then callers can do:

```python
try:
    run_step()
except AppError as e:
    handle_expected_error(e)
```

This avoids `except Exception:` while still providing a single, meaningful “umbrella”.

---

## 4. EAFP vs LBYL

Python style encourages EAFP (Easier to Ask Forgiveness than Permission) — using try/except instead of pre-checking everything — but we still want specificity.

### 4.1. Use EAFP for specific exceptions

### 4.2. Use LBYL sparingly for cheap, obvious checks

For very cheap validations or when the exception would be ambiguous, use LBYL.

Avoid doing heavy or redundant pre-checks that just duplicate what the operation itself will tell you via exceptions.

---

## 5. Conditionals: How to Use `if`, `elif`, `else`

### 5.1. Prefer multiple `if` + early return to giant `if/elif/else`

✅ Preferred:

```python
def categorize(user):
    if user is None:
        return "anonymous"

    if user.is_admin:
        return "admin"

    if user.is_staff:
        return "staff"

    return "user"
```

❌ Less preferred:

```python
def categorize(user):
    if user is None:
        return "anonymous"
    elif user.is_admin:
        return "admin"
    elif user.is_staff:
        return "staff"
    else:
        return "user"
```

Both are valid Python. The first style is preferred here because:

- Each condition stands alone.
- The “fall-through” default path is visually obvious at the end.
- You don’t need to mentally manage the full `if/elif/elif/else` ladder.

### 5.2. When `else` *is* okay

`else` is fine when:

- There are only 1–2 branches and it aids readability.
- The logic is truly binary.

Example:

```python
def normalize_flag(value: str) -> bool:
    value = value.lower().strip()
    if value in {"1", "true", "yes", "y"}:
        return True
    else:
        return False
```

Use judgement: prefer clarity over dogma.

---

## 6. Error Messages and Fail-Fast Behavior

- Fail early and loudly when invariants are broken.
- Raise exceptions with messages that explain what and why, not just that something failed.

✅ Good:

```python
def get_user(id: int) -> User:
    if id <= 0:
        raise ValueError(f"id must be positive, got {id}")
    ...
```

---

## 7. Linting, Pylint, and Broad Exception Rules

We care about linters (e.g. Pylint) and generally do not want to disable rules globally.

- Do not disable warnings

Example:

```python
def worker_loop():
    while True:
        try:
            process_one_job()
        except Exception:  # pylint: disable=broad-exception-caught
            log_exception_and_continue()
```

Use this pattern only where absolutely necessary and structurally justified.

---

## 8. Summary for Agents

When generating or editing code in this repository:

1. Use guard clauses and early returns.
2. Keep control flow flat when possible. Avoid deep nesting and giant `if/elif/else` ladders.
3. Catch specific exceptions, not `Exception`
4. Don’t swallow exceptions silently.
5. Favor small, focused functions that reflect one clear responsibility.

If a simpler structure conflicts with these rules, prioritize clarity and explicitness over cleverness.
