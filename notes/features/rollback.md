# Feature: Week 2 - Rollback, List, and Dependency Resolution

## Features to Implement
1. `satdeploy rollback <app>` - Restore most recent backup
2. `satdeploy rollback <app> <version>` - Restore specific version
3. `satdeploy list <app>` - Show version history from remote backups
4. Dependency resolution (stop/start order)

## Design Decisions

### List Command
- Lists backups from remote `/opt/satdeploy/backups/{app}/` directory
- No local database yet (Week 3)
- Backup filenames follow pattern: `YYYYMMDD-HHMMSS.bak`
- Display format: VERSION, TIMESTAMP columns

### Rollback Command
- Finds backup in `/opt/satdeploy/backups/{app}/`
- Copies backup to remote path
- Restarts services using same stop/start order as push
- Performs health check
- Two modes:
  - No version arg: restore most recent backup
  - With version arg: restore specific backup by timestamp prefix

### Dependency Resolution
- Build dependency graph from config `depends_on` fields
- Stop order: topological sort (dependents first)
- Start order: reverse of stop order
- Also handle `restart` list for libraries

## Implementation Order (TDD)
1. Deployer.list_backups() - list remote backups
2. Deployer.rollback() - restore a backup
3. CLI list command
4. CLI rollback command
5. Dependencies module - graph resolution
6. Integrate deps into push/rollback
