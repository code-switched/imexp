## Plan: Issue #1 Fixes and Preset-Driven Export Roadmap

### Summary
- Treat issue `#1` as two immediate fixes plus one follow-on product milestone.
- Immediate fix 1: make continuous exports clean up `.staging` correctly.
- Immediate fix 2: stop trusting raw upstream name matching; resolve filters locally to exact handles first and fail hard on no match or ambiguity.
- Follow-on milestone: add saved client/project presets in the existing INI config so `imexp` or `imexp export` can run a default preset with no prompt.

### Key Changes
- **Staging cleanup**
  - Keep the current timestamped staging child directory during a continuous export.
  - After a successful merge, remove the staging child and then remove the `.staging` parent if it is empty.
  - If export, post-processing, or merge fails, keep the populated staging directory in place and print its path for inspection; do not silently delete failed work.

- **Strict conversation resolution**
  - Add a local resolver layer before invoking `imessage-exporter`.
  - Resolve each user token against exact normalized handles first, then exact contact-name matches in a case-insensitive way.
  - Rewrite successful matches to canonical handles before building the upstream `--conversation-filter` string.
  - If a token resolves to zero contacts, exit non-zero and create no export output.
  - If a token resolves to multiple contacts, exit non-zero and print the candidate handles so the user can disambiguate.
  - Keep `--conversation-filter` as the public flag, but change its behavior from “raw substring passed upstream” to “strict wrapper-resolved selector”.
  - Do not rely on upstream free-text name matching for safety-critical filtering.

- **Preset-driven v1 workflow**
  - Keep the existing INI file format and extend it instead of migrating to TOML.
  - Add `[export] default_profile = <name>` for the no-arg daily workflow.
  - Add `[profile.<name>]` sections with multiline `handles =` entries as the canonical selector list.
  - Allow optional per-profile overrides for fields that already exist globally: `platform`, `copy_method`, `format`, `use_caller_id`, and `output_dir`.
  - Add `--profile <name>` to `imexp export`.
  - Make `imexp` and `imexp export` with no explicit selector load `default_profile` when configured; this becomes the default daily path instead of the current wizard.
  - Add an explicit `--wizard` escape hatch so interactive prompting still exists when wanted.
  - Make `--profile` and raw `--conversation-filter` mutually exclusive.
  - In v1, group-chat support is approximate by design: listing participant handles in a profile exports direct chats with those people plus group chats containing any of those handles, matching upstream union semantics.
  - Do not add exact group-set sections in v1; leave that for the next milestone once exact chat targeting is tackled.

- **Wizard and docs**
  - If `default_profile` exists, the no-arg path should print which profile is being used and what date window is being applied before export starts.
  - If no default profile exists, keep the current wizard flow.
  - Add a short design note documenting the mission: client-context exports driven by saved participant handles, with exact direct matching and approximate group inclusion in v1.

### Test Plan
- Continuous update removes the timestamped staging child and deletes `.staging` when it becomes empty.
- Failed update preserves a non-empty staging directory and reports it.
- `--conversation-filter` with an exact handle rewrites to that handle in the exporter command.
- `--conversation-filter` with a case-mismatched or ambiguous name does not fall through to a broad export.
- No-match filter exits non-zero and does not create/update export output, history, or metadata.
- `default_profile` makes `imexp` and `imexp export` use the profile without prompting.
- `--wizard` still reaches the current interactive prompt flow.
- `--profile <name>` overrides `default_profile`.
- Profile overrides merge correctly with global defaults and CLI flags.
- Profile `handles` build the upstream union filter expected for approximate group inclusion.

### Assumptions and Defaults
- Keep the current config file and extend it; no format migration.
- Handles are the only canonical matcher in presets; names are for human readability, not authoritative matching.
- No-match behavior is a hard error, not a silent empty success.
- Exact safety is required for direct chats; group-chat inclusion is approximate in v1 because upstream filtering is participant-union, not exact chat selection.
- The next milestone after this plan is exact group targeting, which will likely require a deeper local chat-selection layer and possibly upstream coordination.
