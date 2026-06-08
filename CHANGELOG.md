# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows semantic versioning.

## [0.2.0] - 2026-04-24

### Added
- Saved export profiles with `default_profile` support for no-arg daily exports.
- Strict conversation filter resolution to exact handles before invoking `imessage-exporter`.
- Profile naming metadata with `label`, `slug`, and `names`.
- Profile-scoped filename aliases for friendlier exported chat filenames.

### Changed
- Export folders now prefer profile naming metadata instead of raw resolved handle strings.
- No-arg `imexp` and `imexp export` use the configured default profile when one exists.
- Profile aliases normalize filenames without rewriting message bodies.

### Fixed
- Continuous exports now clean up `.staging` on success.
- Failed continuous exports now preserve staged output for inspection instead of silently removing it.
- Ambiguous or missing conversation selectors now fail loudly instead of broadening export scope.

### Known Limitations
- Group chat inclusion still follows upstream participant-union behavior.
- Cross-profile group chat deduplication is not implemented yet.
- Issue `#2` remains open and is not part of this release.

## [0.1.0] - 2026-03-12

### Added
- First public PyPI release.
- Platform-specific wheels for macOS Apple Silicon, macOS Intel, and Windows x86_64.
- Bundled `imessage-exporter` binaries in official wheels.
- Trusted Publishing flow for TestPyPI and PyPI.

