# Client-Context Exports

`imexp` exists to make repeated client-context exports reliable and lightweight.

The intended daily workflow is:

1. Define a saved profile for each client or project.
2. List the canonical handles that matter for that client.
3. Run `imexp` or `imexp export` and keep one continuously updated export directory per profile.
4. Combine that message history with other communication sources such as email.

This tool is intentionally opinionated about filter safety.

- Handles are canonical.
- Free-text upstream matching is not trusted for wrapper-level filtering.
- Exact direct-chat matching matters more than convenience.
- No-match and ambiguous selectors should fail loudly instead of silently broadening scope.

Profiles are the v1 entry point for this workflow.

- `[export] default_profile = ...` supports a no-arg daily path.
- `[profile.<name>] handles = ...` stores the canonical people tied to a client or project.
- Profile handles currently produce exact direct-chat matches and approximate group-chat inclusion.

That last point is a known limitation, not an accident. Upstream filtering is participant-union
based, so a handle list can include relevant group chats, but it cannot yet express an exact chat
membership set. Exact group targeting is a follow-on milestone.
