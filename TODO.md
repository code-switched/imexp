# TODO List

## Logic

- [ ] Figure out how to append to original file instead of timestamped directories, seems cleaner
- [ ] Remove iOS as a platform, the extra utilities we built make iOS unnecessary. Remove logic and tests related to iOS.
- [ ] Have the model check the codebase structure in `.refs/imessage-exporter.md` and be sure it understands how the underlying binary works and that the flags we are passing match.

## Package

- [ ] Figure out how to bundle the binary of `imessage-exporter` into the package, may include detecting platform, environment, etc
