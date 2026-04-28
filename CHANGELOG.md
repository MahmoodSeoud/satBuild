# Changelog

All notable changes to satdeploy are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version baked into both binaries is taken from `meson.build` and the
git revision at build time:

```
satdeploy-agent --version
satdeploy-apm: csh> satdeploy version
```

Per-component on-the-wire compatibility notes are called out under each
release. **Read these before pushing a new agent to a satellite that has
in-flight (partial) transfers** — the cross-pass resume sidecar is gated by
strict-equality SHA256, so version-mismatched binaries can't silently
inherit a stale bitmap.

## [Unreleased]

### Added
- Quick-recipe block in `satdeploy help` (push, status, rollback, list, logs)
- "Another agent on this CSP node?" hint when `satdeploy-agent` fails to bind
  port 20

### Documentation
- `CHANGELOG.md` — this file
- `CONTRIBUTING.md` — build, test, and submodule pinning workflow
- `.github/ISSUE_TEMPLATE/` — bug report and feature request templates

## [0.4.0] — 2026-04-28

The CSP-only release. The Python CLI is gone; everything ground-side runs
through the APM inside CSH. Cross-pass resumable transfers are the headline
feature for flight operations.

### Added
- **Cross-pass resumable DTP transfers.** A partial transfer that exhausts
  its retry budget within a pass writes its receive bitmap to
  `/var/lib/satdeploy/state/<app>.dtpstate` (mode 0600). The next push for
  the same `(app, expected_hash)` pre-patches `request_meta.intervals[]` so
  only the still-missing seqs go on the wire. Strict-equality SHA256 gating
  prevents a re-staged binary from inheriting a stale bitmap.
- **Full 64-hex SHA256 on the wire.** `expected_checksum` carries the full
  hash (was 8-char prefix). 8-char display is preserved in status/list
  tables for readability. The agent rejects undersized checksums with a
  version-skew hint.
- `--version` flag on the agent (via meson `configure_file`)
- `version.h.in` for both components — APM and agent both report
  `<version> (<git-rev>)`

### Changed
- DTP defaults tuned for localhost ZMQ + larger payloads
- Re-request only the missing intervals on incomplete transfers (not the
  whole file)
- Redesigned `status` / `push` / `list` / `rollback` / `config` output

### Removed
- **Python CLI deleted.** `satdeploy/cli.py`, the SSH transport, the PyPI
  publish workflow, and the dual-implementation test matrix are gone. CSP
  is the only ground-side path now. If SSH is needed in the future, it
  comes back as a separate component, not by reviving the old layout.
- Stale Docker compose stack and obsolete design docs

### Wire compatibility
- **Hash format:** `expected_checksum` field is now 64-hex SHA256. Older
  agents that expected 8-char will reject these requests; older APMs that
  send 8-char will be rejected by 0.4.0 agents with an explicit hint.
  **Coordinate the upgrade — bump APM and agent together.**
- **Sidecar format:** new in this release. See
  `satdeploy-agent/include/session_state.h` for the on-disk layout. No
  format from prior versions; nothing to migrate.

## [0.3.13] — 2026-04-14

### Fixed
- `status`: rename bogus `DEPLOYED` column to `HASH`

## [0.3.12] — 2026-04-14

### Changed
- `status`: drop redundant target header

## [0.3.11] — 2026-04-14

### Documentation
- README hero crop (DISCO-2 horizon sunrise)

## [0.3.10] — 2026-04-14

### Changed
- `status`: promote remote path to its own `PATH` column

## [0.3.9] — 2026-04-14

### Changed
- `status`: clearer table layout (`STATE`, `TIMESTAMP`, `path`)

## [0.3.6 – 0.3.8] — 2026-04-14

### Added
- LocalTransport for dockerless flatsat workflows
- `--require-clean` enforcement for non-git binaries (was silently passing)
- `--version` flag on the CLI

### Changed
- README rewritten for the dockerless flatsat-first story
- `--force` no longer pollutes the backup chain on identical-file pushes
- More honest CLI errors: surface hash-skip and restore-from-backup paths

## [0.3.5] and earlier — 2026-03 to 2026-04

Active CLI development phase. Highlights from this period that survived
into 0.4.0 (everything else was deleted with the Python CLI):

### Added
- CSP transport with DTP (replacing the early SSH-only path)
- Tab completion for app names in CLI and APM
- Git provenance tracking on every push
- Yocto recipe layer (`meta-satdeploy/`) for distributing the agent
- `apm load` / unified slash command surface inside CSH

### Fixed
- DTP server race condition on small files
- Type mismatch in `dtp_download_file` that corrupted `payload_id`
- `csp_iflist`-based ground node resolution (was reading `csp_conf`)
- DTP/CSH symbol shadowing — APM now uses headers-only `partial_dependency`
  so its statically-linked DTP doesn't shadow CSH's

## [0.1.0] — 2026-03-23

Initial public release. Python CLI + early CSP/SSH transports, since
deleted. Tagged releases existed but the line is not on a maintained
upgrade path — anyone on 0.1.x or 0.2.x should jump directly to 0.4.0.

[Unreleased]: https://github.com/MahmoodSeoud/satDeploy/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/MahmoodSeoud/satDeploy/compare/v0.3.13...v0.4.0
[0.3.13]: https://github.com/MahmoodSeoud/satDeploy/compare/v0.3.12...v0.3.13
[0.3.12]: https://github.com/MahmoodSeoud/satDeploy/compare/v0.3.11...v0.3.12
[0.3.11]: https://github.com/MahmoodSeoud/satDeploy/compare/v0.3.10...v0.3.11
[0.3.10]: https://github.com/MahmoodSeoud/satDeploy/compare/v0.3.9...v0.3.10
[0.3.9]: https://github.com/MahmoodSeoud/satDeploy/compare/v0.3.8...v0.3.9
[0.1.0]: https://github.com/MahmoodSeoud/satDeploy/releases/tag/v0.1.0
