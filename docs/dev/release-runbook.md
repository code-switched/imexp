# Release Runbook

This runbook is the canonical checklist for shipping `imexp` releases to TestPyPI, PyPI, and GitHub.

## Terms

- `release runbook`: the full release procedure with commands and decisions.
- `release checklist`: the short preflight list extracted from the runbook.
- `launch notes`: public-facing highlights for GitHub Releases, PyPI, or announcements.

## Versioning

Use semantic versioning.

- `patch`: docs-only fixes, packaging fixes, small non-user-facing corrections
- `minor`: new user-facing features and fixes
- `major`: breaking changes

For the current branch, the next release is `0.2.0`.

## Preflight

Before touching tags:

1. Make sure the working tree is clean.
2. Run `./.venv/bin/pytest -q`.
3. Confirm `main` contains everything intended for the release.
4. Update [CHANGELOG.md](/Users/dev/code/tools/imexp/CHANGELOG.md).
5. Bump the version in [pyproject.toml](/Users/dev/code/tools/imexp/pyproject.toml).
6. Confirm issue-closing intent.

## Issue References

Put closing keywords in the PR body, not only in commit messages.

- Use `Closes #<n>` for issues that should auto-close on merge.
- Use `Refs #<n>` for related issues that should stay open.

For `0.2.0`:

- `Closes #1`
- `Refs #2`

## Branching

Cut a dedicated release branch from `main`.

Example:

```bash
git checkout main
git pull --ff-only
git checkout -b release-0.2.0
```

## Release Preparation

Make the release edits:

```bash
./.venv/bin/pytest -q
git add pyproject.toml CHANGELOG.md docs/dev/release-runbook.md
git commit -m "build(release): prepare 0.2.0" -m "- bump the package version to 0.2.0
- add release notes to the changelog
- document the release procedure and issue-closing rules"
```

## Pull Request

Open a PR from the release branch into `main`.

Suggested title:

```text
Release 0.2.0
```

Suggested body:

```md
## Summary

- ship profile-driven exports and strict selector resolution
- add profile labels, slugs, and filename aliases
- fix continuous export staging cleanup
- document the release process and changelog

## Verification

- `./.venv/bin/pytest -q`
- GitHub Actions CI green
- TestPyPI release smoke-tested before production tag

Closes #1
Refs #2
```

## Merge Gate

Before merge:

1. CI from [ci.yml](/Users/dev/code/tools/imexp/.github/workflows/ci.yml) must be green.
2. The changelog entry must match the shipped changes.
3. The version in [pyproject.toml](/Users/dev/code/tools/imexp/pyproject.toml) must match the intended tag.
4. The PR body must contain the correct issue keywords.

## TestPyPI

After the PR merges to `main`, run the release workflow manually.

GitHub UI:

1. Go to `Actions`.
2. Open `Release`.
3. Click `Run workflow`.
4. Choose `main`.
5. Run it.

CLI alternative:

```bash
gh workflow run Release --ref main
```

This triggers [release.yml](/Users/dev/code/tools/imexp/.github/workflows/release.yml) in `workflow_dispatch` mode and publishes to TestPyPI.

## Smoke Test

After TestPyPI is green:

1. Create a clean macOS virtual environment.
2. Install from TestPyPI.
3. Verify `imexp -h`.
4. Verify `imexp export -h`.
5. Run one small real export if practical.
6. Repeat on Windows if the release contains Windows wheel changes.

Example install:

```bash
python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple imexp==0.2.0
```

## Production Tag

After TestPyPI verification:

```bash
git checkout main
git pull --ff-only
git tag -s v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

The tag push triggers the same workflow and publishes to the `pypi` environment.

## GitHub Release

After PyPI is confirmed live, create a GitHub Release.

Example:

```bash
gh release create v0.2.0 --title "v0.2.0" --notes-file CHANGELOG.md
```

If you want tighter notes, prepare a short release-note file from the `0.2.0` changelog section and use that instead.

## Post-Release Verification

After publication:

1. Confirm the new version is visible on PyPI.
2. Install from real PyPI in a clean virtual environment.
3. Confirm the expected wheel is selected on macOS and Windows.
4. Confirm the `v0.2.0` GitHub Release exists.
5. Confirm issue `#1` is closed.
6. Confirm issue `#2` remains open.

## Rollback Rule

PyPI releases are immutable.

If a bad release ships:

1. Do not try to overwrite the existing version.
2. Cut a new version immediately.
3. Document the correction in the changelog.

## Short Checklist

Use this as the fast path:

1. Bump version.
2. Update changelog.
3. Run tests.
4. Open release PR with closing keywords.
5. Merge to `main`.
6. Run TestPyPI release.
7. Smoke test.
8. Sign and push tag.
9. Verify PyPI.
10. Create GitHub Release.
