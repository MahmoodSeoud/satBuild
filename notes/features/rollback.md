# Feature: Week 2 - Rollback, List, and Dependency Resolution

## Status: COMPLETED

All Week 2 features have been implemented and tested.

## Features Implemented
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
- Cyclic dependency detection added

## Implementation Order (TDD)
1. [x] Deployer.list_backups() - list remote backups
2. [x] Deployer.rollback() - restore a backup
3. [x] CLI list command
4. [x] CLI rollback command
5. [x] Dependencies module - graph resolution
6. [x] Integrate deps into push/rollback

## Tests Added
- 130 total tests now passing
- test_deployer.py: TestListBackups, TestRollback classes
- test_cli_list.py: TestListCommand class
- test_cli_rollback.py: TestRollbackCommand, TestRollbackWithDependencies classes
- test_dependencies.py: TestBuildGraph, TestStopOrder, TestStartOrder,
  TestRestartList, TestCyclicDependencyDetection classes
- test_cli_push.py: TestPushWithDependencies class
