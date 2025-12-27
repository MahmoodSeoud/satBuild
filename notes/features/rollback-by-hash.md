# Feature: Rollback by Hash

## Summary
Allow `satdeploy rollback <app> <hash>` to rollback by specifying just the 8-character hash prefix instead of the full version string.

## Current Behavior
- `satdeploy rollback controller` - dial behavior, goes to next older version
- `satdeploy rollback controller 20240114-091500-def67890` - matches full version string

## Desired Behavior
- Support rollback by hash: `satdeploy rollback controller def67890`
- Should find the backup with matching hash prefix
- Error if hash not found or ambiguous

## Implementation Notes
- Version arg lookup in cli.py lines 622-627 searches `raw_backups` by `b["version"]`
- Need to add fallback search by `b.get("hash")` when version string doesn't match
- Hash is 8 characters, version string is longer (timestamp-hash format)

## Test Cases
1. Rollback by valid hash prefix finds correct backup
2. Rollback by unknown hash fails with "not found" error
3. Full version string still works (backward compat)
